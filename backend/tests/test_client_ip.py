"""The address recorded against a session.

The per-device list is the screen a user consults when they think someone else
is in their account, so the address on it has to mean something. These tests pin
both halves of that: a direct client cannot choose its own, and a real proxy's
header is honoured exactly when it should be.
"""

import pytest

from extensions import db
from models import UserSession
from tests.conftest import TestConfig


class _ProxyConfig(TestConfig):
    """One trusted proxy, as a load balancer deployment would run.

    Subclasses TestConfig rather than Config so it inherits the safe test
    defaults -- notably BREACH_CHECK_ENABLED=False, since a local config that
    reached the real Have I Been Pwned API made registration fail for a password
    that genuinely is in that corpus.
    """

    PROXY_FIX_X_FOR = 1


@pytest.fixture
def proxied_client(app):
    """A second app configured as if behind one trusted proxy.

    Reuses the session-scoped schema rather than building its own, and must not
    drop the tables on the way out: against a real database server this app points
    at the *same* database as the shared one, so a drop_all() here tears down the
    schema that every later test depends on. On in-memory SQLite the engine is
    private and the same drop would be harmless, which is exactly the kind of
    difference that only shows up in CI.
    """
    from sqlalchemy import inspect as sa_inspect

    from app import create_app
    from extensions import db

    application = create_app(_ProxyConfig)
    with application.app_context():
        db.session.remove()
        if not sa_inspect(db.engine).has_table("user"):
            db.create_all()
        yield application.test_client()
        db.session.remove()


def _register_and_login(client, username="alice"):
    client.post("/auth/register", json={"username": username, "password": "correct-horse"})
    return client.post(
        "/auth/login", json={"username": username, "password": "correct-horse"}
    )


def _stored_ip(client):
    return client.get("/account/sessions").json["sessions"][0]["ip_address"]


class TestAddressCannotBeForged:
    def test_a_direct_client_cannot_choose_its_address(self, client, app):
        _register_and_login(client)

        # PROXY_FIX_X_FOR is 0, so no proxy is trusted and the header means
        # nothing. Before the fix this exact string was stored.
        client.post(
            "/auth/login",
            json={"username": "alice", "password": "correct-horse"},
            headers={"X-Forwarded-For": "203.0.113.99"},
        )

        addresses = [s["ip_address"] for s in client.get("/account/sessions").json["sessions"]]
        assert "203.0.113.99" not in addresses, (
            "a client chose the address stored against its own session"
        )

    def test_no_proxy_configured_ignores_the_header_entirely(self, client, app):
        _register_and_login(client)
        client.post(
            "/auth/login",
            json={"username": "alice", "password": "correct-horse"},
            headers={"X-Forwarded-For": "198.51.100.7"},
        )

        with app.app_context():
            for row in UserSession.query.all():
                assert row.ip_address != "198.51.100.7"

    def test_the_loopback_peer_is_recorded_instead(self, client):
        _register_and_login(client)
        # The test client connects over loopback, so that is what is stored.
        assert _stored_ip(client) == "127.0.0.1"

    def test_a_missing_header_is_not_an_error(self, client):
        assert _register_and_login(client).status_code == 200
        assert _stored_ip(client) is not None

    def test_an_overlong_address_is_truncated_to_fit_the_column(self, app):
        """A hostile X-Forwarded-For must not reach the column unshortened.

        Not reachable through the app now that the header is ignored, but
        start_session still truncates, and the column is only 45 characters.
        """
        from models import User
        from passwords import hash_password

        with app.app_context():
            user = User(username="alice", password_hash=hash_password("correct-horse"))
            db.session.add(user)
            db.session.flush()
            session = user.start_session(
                user_agent="probe",
                ip_address="9" * 400,
            )
            db.session.commit()
            assert len(session.ip_address) == 45

    def test_an_overlong_user_agent_is_truncated_too(self, app):
        from models import User
        from passwords import hash_password

        with app.app_context():
            user = User(username="alice", password_hash=hash_password("correct-horse"))
            db.session.add(user)
            db.session.flush()
            session = user.start_session(user_agent="x" * 5000, ip_address="127.0.0.1")
            db.session.commit()
            assert len(session.user_agent) == 200


class TestProxyHeaderIsHonouredWhenConfigured:
    def test_the_proxied_client_address_is_recorded(self, proxied_client):
        # One trusted proxy appends the real peer to the header. ProxyFix takes
        # the last value before its own trusted hop.
        _register_and_login(proxied_client)
        proxied_client.post(
            "/auth/login",
            json={"username": "alice", "password": "correct-horse"},
            headers={"X-Forwarded-For": "203.0.113.99"},
        )

        addresses = [s["ip_address"] for s in proxied_client.get("/account/sessions").json["sessions"]]
        assert "203.0.113.99" in addresses, (
            "with PROXY_FIX_X_FOR=1 the proxy's header should be honoured"
        )

    def test_a_chain_is_unwound_the_configured_depth(self, proxied_client):
        _register_and_login(proxied_client)
        proxied_client.post(
            "/auth/login",
            json={"username": "alice", "password": "correct-horse"},
            headers={"X-Forwarded-For": "203.0.113.99, 198.51.100.7"},
        )

        addresses = [s["ip_address"] for s in proxied_client.get("/account/sessions").json["sessions"]]
        # Depth 1 means the rightmost entry is the only one trusted.
        assert "198.51.100.7" in addresses
