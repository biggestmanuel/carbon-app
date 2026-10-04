import os
import sys
from datetime import timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config  # noqa: E402
from totp import current_code  # noqa: E402

# The suite runs against whatever TEST_DATABASE_URL names, so the Postgres CI
# job exercises the same tests on the engine production uses.
#
# Deliberately not DATABASE_URL: that is what `flask db upgrade` and the running
# app read, and this fixture drops every table between tests. Sharing the name
# would mean a developer who exported DATABASE_URL for their dev database lost
# it to a test run. TEST_DATABASE_URL has to be set on purpose.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "sqlite://")


class TestConfig(Config):
    """Overrides the app factory's defaults for tests.

    Subclasses the real Config so create_app() finds validate() and the
    production guard rails still apply.
    """

    ENV = "development"
    TESTING = True
    SQLALCHEMY_DATABASE_URI = TEST_DATABASE_URL
    AUTO_CREATE_TABLES = False
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=5)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=1)
    JWT_COOKIE_SECURE = False
    # Rate limits are exercised explicitly in test_ratelimit.py; leave them off
    # everywhere else so unrelated tests are not throttled by ordering.
    RATELIMIT_ENABLED = False
    # The breach check calls a third party over the network. Tests must never
    # depend on someone else's availability, and "correct-horse" is genuinely in
    # that corpus, so leaving this on made every registration fail for real.
    BREACH_CHECK_ENABLED = False

    # A fixed key so the TOTP tests can assert on ciphertext without depending on
    # a value generated per run. Not a real deployment key: tests only ever
    # encrypt and decrypt within one process, and this string is in the repo.
    # A valid Fernet key: 32 url-safe base64-encoded bytes, which is 44
    # characters with one '=' of padding. A test asserting that a plaintext seed
    # is *not* in the column needs a working key, not a plausible-looking string.
    TOTP_ENCRYPTION_KEY = b"YVGGsJ3cy-WpnsE3YfNtl84-mzfpW9kTcuD0y6mqNjA="
    TOTP_RECOVERY_CODES = 10


@pytest.fixture
def totp_key():
    """Assert a ciphertext is encrypted, using the suite's fixed key.

    Decrypts rather than pattern-matching the stored string: the property worth
    protecting is that the plaintext is recoverable only with the key, and a
    decode is the only check that actually demonstrates it.
    """
    from cryptography.fernet import Fernet

    from tests.conftest import TestConfig

    return Fernet(TestConfig.TOTP_ENCRYPTION_KEY)


@pytest.fixture
def enroll_mfa(client):
    """Turn 2FA on for the logged-in user and return (secret, recovery_codes).

    Drives the real endpoints rather than writing the row directly, so the tests
    that use it also cover the API surface they are about.
    """
    def _enroll():
        start = client.get("/auth/mfa/start")
        assert start.status_code == 200, start.get_json()
        secret = start.get_json()["secret"]

        confirm = client.post("/auth/mfa/confirm", json={
            "secret": secret, "code": current_code(secret),
        })
        assert confirm.status_code == 200, confirm.get_json()
        return secret, confirm.get_json()["recovery_codes"]

    return _enroll


@pytest.fixture
def login(client):
    """POST /auth/login and return the response, whatever shape it takes."""
    def _login(username="alice", password="correct-horse"):
        return client.post("/auth/login", json={"username": username, "password": password})

    return _login


@pytest.fixture
def enable_totp(client, auth_headers, enroll_mfa, login):
    """An enrolled account, with a helper to complete the second login step."""
    def _setup(password="correct-horse"):
        auth_headers(password=password)
        secret, recovery_codes = enroll_mfa()
        return secret, recovery_codes

    return _setup


@pytest.fixture
def finish_mfa_login(client):
    """Complete a pending login with a code."""
    def _finish(pending_token, code):
        return client.post("/auth/mfa/check", json={
            "pending_token": pending_token, "code": code,
        })

    return _finish


def _empty_every_table():
    """Delete all rows, children before parents.

    Ordered by the metadata rather than by name because Postgres enforces the
    foreign keys that SQLite ignores, so a parent-first delete would fail there.
    `sorted_tables` lists parents first, hence reversed.
    """
    from extensions import db

    for table in reversed(db.metadata.sorted_tables):
        db.session.execute(table.delete())


@pytest.fixture(scope="session")
def _schema():
    """Build the schema once for the whole run.

    Recreating it per test meant ~200 CREATE/DROP rounds, which is tolerable on
    in-memory SQLite and painfully slow against a real server.
    """
    from app import create_app
    from extensions import db

    application = create_app(TestConfig)
    with application.app_context():
        db.session.remove()
        db.create_all()
    yield application
    with application.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def app(_schema):
    from extensions import db

    with _schema.app_context():
        db.session.remove()
        _empty_every_table()
        db.session.commit()
        yield _schema
        db.session.remove()
        _empty_every_table()
        db.session.commit()


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
