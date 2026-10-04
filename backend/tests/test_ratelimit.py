"""Rate limiting on the credential endpoints.

Flask-Limiter skips throttling when RATELIMIT_ENABLED is off or TESTING is set,
so these tests enable it explicitly and use a fresh in-memory store each time.
"""
import os

import pytest

from config import Config

# Same source as tests/conftest.py. Read from the environment rather than
# imported, because importing conftest as a module relies on it being an
# importable package, which it is not declared to be.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "sqlite://")


class LimitedConfig(Config):
    """Tight limits so the tests need only a handful of requests.

    RATELIMIT_ENABLED is on, so throttling is genuinely exercised rather than
    bypassed by a test-mode exemption. Subclasses Config rather than the shared
    TestConfig on purpose: TestConfig sets TESTING, and Flask-Limiter skips
    throttling entirely when TESTING is set.
    """

    ENV = "development"
    SQLALCHEMY_DATABASE_URI = TEST_DATABASE_URL
    AUTO_CREATE_TABLES = False
    JWT_COOKIE_SECURE = False
    RATELIMIT_ENABLED = True
    RATELIMIT_STORAGE_URI = "memory://"
    LOGIN_RATE_LIMIT = "5 per minute"
    REGISTER_RATE_LIMIT = "3 per hour"
    CALCULATE_RATE_LIMIT = "4 per minute"
    READ_RATE_LIMIT = "6 per minute"


@pytest.fixture
def limited_client():
    """A second app, because RATELIMIT_ENABLED is latched at init_app.

    Changing it on the shared app afterwards does not work: Flask-Limiter builds
    and caches a limit object per view on first request, so toggling the flag
    mid-run left the routes unthrottled and stopped the headers being injected.

    A second app means a second engine. On in-memory SQLite that engine points at
    a private, empty database, so the schema is created for it; against a real
    server the schema already exists and is owned by conftest, so it is left
    alone and only the rows are cleared.
    """
    from sqlalchemy import inspect as sa_inspect

    from app import create_app
    from extensions import db
    from tests.conftest import _empty_every_table

    application = create_app(LimitedConfig)
    with application.app_context():
        db.session.remove()
        if not sa_inspect(db.engine).has_table("user"):
            db.create_all()
        _empty_every_table()
        db.session.commit()
        yield application.test_client()
        db.session.remove()
        _empty_every_table()
        db.session.commit()


BAD_LOGIN = {"username": "ratetest", "password": "wrong-password"}


def _register(client, username="ratetest", password="correct-horse"):
    return client.post("/auth/register", json={"username": username, "password": password})


def test_login_is_rate_limited(limited_client):
    _register(limited_client)
    statuses = [limited_client.post("/auth/login", json=BAD_LOGIN).status_code for _ in range(8)]
    assert 429 in statuses, f"expected a 429, got {statuses}"
    assert 401 in statuses, "first attempts should still be rejected normally"


def test_rate_limited_response_is_json(limited_client):
    _register(limited_client)
    for _ in range(8):
        res = limited_client.post("/auth/login", json=BAD_LOGIN)
        if res.status_code == 429:
            break
    assert res.status_code == 429
    assert res.json["code"] == "rate_limited"
    assert res.json["msg"]


def test_rate_limit_headers_present(limited_client):
    _register(limited_client)
    res = None
    for _ in range(8):
        res = limited_client.post("/auth/login", json={"username": "ratetest", "password": "wrong-password"})
        if res.status_code == 429:
            break
    assert res.status_code == 429
    assert "Retry-After" in res.headers
    assert "X-RateLimit-Limit" in res.headers


def test_register_is_rate_limited(limited_client):
    statuses = [_register(limited_client, f"user{i}").status_code for i in range(6)]
    assert 429 in statuses, f"expected a 429, got {statuses}"


def test_calculate_is_rate_limited(limited_client):
    _register(limited_client)
    limited_client.post("/auth/login", json={"username": "ratetest", "password": "correct-horse"})
    payload = {"car_km": 1, "electricity_kwh": 1, "meat_meals": 1, "plant_meals": 1}
    statuses = [limited_client.post("/footprint/calculate", json=payload).status_code for _ in range(8)]
    assert 429 in statuses, f"expected a 429, got {statuses}"


def test_health_is_not_rate_limited(limited_client):
    # Deliberate. A load balancer polling /health must never see a 429, or it
    # may pull a healthy instance out of rotation.
    for _ in range(20):
        assert limited_client.get("/health").status_code == 200


def test_factors_catalogue_is_rate_limited(limited_client):
    # Unauthenticated, and it returns the whole region table every time.
    statuses = [limited_client.get("/footprint/factors").status_code for _ in range(8)]
    assert 429 in statuses, f"expected a 429, got {statuses}"


def test_limits_disabled_when_flag_off(client):
    """The default test config disables limiting; unrelated tests must not flake."""
    assert client.application.config["RATELIMIT_ENABLED"] is False
    client.post("/auth/register", json={"username": "alice", "password": "correct-horse"})
    for _ in range(30):
        assert client.post("/auth/login", json=BAD_LOGIN).status_code == 401
