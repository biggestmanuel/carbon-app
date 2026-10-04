import os
import sys
from datetime import timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config  # noqa: E402

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
