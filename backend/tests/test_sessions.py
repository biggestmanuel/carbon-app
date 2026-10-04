"""Session lifecycle: what happens to `user_session` rows over time.

Every test here is about a row that was left behind rather than removed. The
table is the backing store for the per-device list users are told to check when
they suspect someone else is in their account, so a stale row is worse than a
missing one: it looks like a live session.
"""

from datetime import timedelta

import pytest
from flask_jwt_extended import create_access_token

from models import User, UserSession


def _expired_access_cookie(app, user, session_id):
    """A validly signed access token that expired an hour ago.

    Breaking the signature would test the wrong thing, since an unverifiable
    token is supposed to be refused.
    """
    return create_access_token(
        identity=str(user.id),
        additional_claims={
            app.config["JWT_SESSION_VERSION_CLAIM"]: user.token_version or 1,
            app.config["JWT_SESSION_ID_CLAIM"]: session_id,
        },
        expires_delta=timedelta(hours=-1),
    )


class TestPasswordResetClearsSessions:
    def test_reset_removes_every_session_row(self, client, app):
        # Register with an address, confirm it, then reset.
        client.post("/auth/register", json={
            "username": "alice", "password": "correct-horse",
            "email": "alice@example.com",
        })
        client.post("/auth/login", json={"username": "alice", "password": "correct-horse"})
        token = client.post("/account/verify-email/request").json["dev_token"]
        client.post("/account/verify-email/confirm", json={"token": token})
        client.post("/auth/logout")

        # Three devices. Logging out between logins would delete each row, so
        # they are created back to back instead.
        for _ in range(3):
            client.post("/auth/login", json={"username": "alice", "password": "correct-horse"})
        assert len(client.get("/account/sessions").json["sessions"]) == 3

        reset = client.post("/auth/forgot-password", json={"email": "alice@example.com"})
        assert reset.status_code == 202
        res = client.post("/auth/reset-password", json={
            "token": reset.json["dev_token"], "password": "new-password-1",
        })
        assert res.status_code == 200

        # The rows must be gone, not merely unusable.
        with app.app_context():
            assert UserSession.query.count() == 0

    def test_reset_leaves_no_dead_rows_in_the_list(self, client, app):
        client.post("/auth/register", json={
            "username": "alice", "password": "correct-horse",
            "email": "alice@example.com",
        })
        client.post("/auth/login", json={"username": "alice", "password": "correct-horse"})
        token = client.post("/account/verify-email/request").json["dev_token"]
        client.post("/account/verify-email/confirm", json={"token": token})
        client.post("/auth/logout")

        for _ in range(3):
            client.post("/auth/login", json={"username": "alice", "password": "correct-horse"})
        assert len(client.get("/account/sessions").json["sessions"]) == 3

        reset = client.post("/auth/forgot-password", json={"email": "alice@example.com"})
        client.post("/auth/reset-password", json={
            "token": reset.json["dev_token"], "password": "new-password-1",
        })

        # Log back in: the list must show only the new device.
        client.post("/auth/login", json={"username": "alice", "password": "new-password-1"})
        listed = client.get("/account/sessions").json["sessions"]
        assert len(listed) == 1, "stale rows from before the reset are still listed"

    def test_reset_of_one_user_does_not_touch_another(self, client, app):
        client.post("/auth/register", json={
            "username": "alice", "password": "correct-horse",
            "email": "alice@example.com",
        })
        client.post("/auth/login", json={"username": "alice", "password": "correct-horse"})
        token = client.post("/account/verify-email/request").json["dev_token"]
        client.post("/account/verify-email/confirm", json={"token": token})
        client.post("/auth/logout")
        reset = client.post("/auth/forgot-password", json={"email": "alice@example.com"})
        raw = reset.json["dev_token"]

        client.post("/auth/logout")
        client.post("/auth/register", json={"username": "bob", "password": "another-password"})
        client.post("/auth/login", json={"username": "bob", "password": "another-password"})
        bob_sessions = client.get("/account/sessions").json["sessions"]
        assert len(bob_sessions) == 1

        client.post("/auth/reset-password", json={"token": raw, "password": "new-password-1"})

        with app.app_context():
            bob = User.query.filter_by(username="bob").one()
            assert UserSession.query.filter_by(user_id=bob.id).count() == 1, (
                "alice's reset removed bob's session"
            )


class TestLogoutIsIdempotent:
    def test_logout_succeeds_with_an_expired_access_cookie(self, client, app):
        client.post("/auth/register", json={"username": "alice", "password": "correct-horse"})
        client.post("/auth/login", json={"username": "alice", "password": "correct-horse"})

        with app.app_context():
            user = User.query.filter_by(username="alice").one()
            session = UserSession.query.filter_by(user_id=user.id).one()
            expired = _expired_access_cookie(app, user, session.id)

        client.set_cookie("access_token_cookie", expired, domain="localhost")
        res = client.post("/auth/logout")

        # The regression: @jwt_required() verified expiry before the view ran and
        # answered 401, which is exactly when a user most wants to log out.
        assert res.status_code == 200
        with app.app_context():
            assert UserSession.query.count() == 0, "the row outlived the logout"

    def test_logout_clears_the_cookies_even_when_the_token_is_expired(self, client, app):
        client.post("/auth/register", json={"username": "alice", "password": "correct-horse"})
        client.post("/auth/login", json={"username": "alice", "password": "correct-horse"})

        with app.app_context():
            user = User.query.filter_by(username="alice").one()
            session = UserSession.query.filter_by(user_id=user.id).one()
            expired = _expired_access_cookie(app, user, session.id)

        client.set_cookie("access_token_cookie", expired, domain="localhost")
        cleared = " ".join(client.post("/auth/logout").headers.getlist("Set-Cookie"))
        assert "access_token_cookie=;" in cleared
        # Werkzeug expires the cookie in the past rather than sending Max-Age=0.
        assert "1970" in cleared

    def test_logout_with_no_cookie_at_all_still_succeeds(self, client):
        assert client.post("/auth/logout").status_code == 200

    def test_logout_with_a_tampered_token_still_succeeds(self, client):
        # An unverifiable token cannot be trusted to identify a session, so the
        # row must survive; the cookies must still be cleared.
        client.post("/auth/register", json={"username": "alice", "password": "correct-horse"})
        client.post("/auth/login", json={"username": "alice", "password": "correct-horse"})

        client.set_cookie("access_token_cookie", "not.a.jwt", domain="localhost")
        res = client.post("/auth/logout")

        assert res.status_code == 200
        # The row is deliberately left alone: nothing vouched for it.
        assert client.get("/auth/me").status_code == 401

    def test_a_token_cannot_log_out_another_users_session(self, client, app):
        client.post("/auth/register", json={"username": "alice", "password": "correct-horse"})
        client.post("/auth/login", json={"username": "alice", "password": "correct-horse"})
        # No logout here: it would delete alice's row, and the point is that the
        # row still exists when bob's forged token reaches for it.
        client.post("/auth/register", json={"username": "bob", "password": "another-password"})
        client.post("/auth/login", json={"username": "bob", "password": "another-password"})

        with app.app_context():
            alice = User.query.filter_by(username="alice").one()
            alice_session = UserSession.query.filter_by(user_id=alice.id).one()
            # Bob's token, carrying Alice's session id.
            bob = User.query.filter_by(username="bob").one()
            bob_session = UserSession.query.filter_by(user_id=bob.id).one()
            forged = create_access_token(
                identity=str(bob.id),
                additional_claims={
                    app.config["JWT_SESSION_VERSION_CLAIM"]: bob.token_version or 1,
                    app.config["JWT_SESSION_ID_CLAIM"]: alice_session.id,
                },
            )
            assert alice_session.id != bob_session.id

        client.set_cookie("access_token_cookie", forged, domain="localhost")
        assert client.post("/auth/logout").status_code == 200

        with app.app_context():
            assert UserSession.query.filter_by(id=alice_session.id).count() == 1, (
                "a token deleted a session belonging to another user"
            )


class TestSignOutEverywhere:
    def test_clears_rows_and_bumps_the_version(self, client, app):
        client.post("/auth/register", json={"username": "alice", "password": "correct-horse"})
        for _ in range(3):
            client.post("/auth/login", json={"username": "alice", "password": "correct-horse"})
        assert len(client.get("/account/sessions").json["sessions"]) == 3

        assert client.delete("/account/sessions").status_code == 200

        with app.app_context():
            assert UserSession.query.count() == 0
            assert User.query.filter_by(username="alice").one().token_version > 1


@pytest.mark.parametrize("method,path", [
    ("get", "/account/sessions"),
    ("delete", "/account/sessions"),
])
def test_session_endpoints_require_a_session(client, method, path):
    assert getattr(client, method)(path).status_code == 401
