import os
import sys
from datetime import timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config  # noqa: E402


class TestConfig(Config):
    """Overrides the app factory's defaults for tests.

    Subclasses the real Config so create_app() finds validate() and the
    production guard rails still apply.
    """

    ENV = "development"
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    AUTO_CREATE_TABLES = False
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=5)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=1)
    JWT_COOKIE_SECURE = False
    # Rate limits are exercised explicitly in test_ratelimit.py; leave them off
    # everywhere else so unrelated tests are not throttled by ordering.
    RATELIMIT_ENABLED = False


@pytest.fixture
def app():
    from app import create_app
    from extensions import db

    application = create_app(TestConfig)
    with application.app_context():
        db.session.remove()
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_headers(client):
    """Register + log in, returning the cookies the app would receive."""
    def _make(username="alice", password="correct-horse"):
        client.post("/auth/register", json={"username": username, "password": password})
        res = client.post("/auth/login", json={"username": username, "password": password})
        assert res.status_code == 200, res.get_json()
        return res

    return _make


@pytest.fixture
def logged_in(client, auth_headers):
    """A logged-in client, so cookie tests do not re-auth on every call."""
    auth_headers()
    return client


@pytest.fixture
def valid_payload():
    return {"car_km": 100, "electricity_kwh": 200, "meat_meals": 3, "plant_meals": 5}
