"""Password reset over HTTP.

Two properties matter more than the happy path:
  1. /auth/forgot-password must not reveal whether an address exists.
  2. A token must work exactly once, and expire.
"""

from datetime import UTC, datetime, timedelta

import pytest

from models import User
from passwords import TOKEN_TTL, generate_token


@pytest.fixture
def user_with_email(client):
    client.post("/auth/register", json={
        "username": "alice", "password": "correct-horse", "email": "Alice@Example.com",
    })
    return "alice"


def _reset(client, address="alice@example.com"):
    return client.post("/auth/forgot-password", json={"email": address})


class TestRegistrationEmail:
    def test_accepts_and_normalises_an_email(self, client):
        res = client.post("/auth/register", json={
            "username": "bob", "password": "correct-horse", "email": "Bob@Example.COM",
        })
        assert res.status_code == 201
        assert res.json["can_reset_password"] is True

    def test_email_is_optional(self, client):
        res = client.post("/auth/register", json={"username": "bob", "password": "correct-horse"})
        assert res.status_code == 201
        # Nothing to send a link to, so the client must be told.
        assert res.json["can_reset_password"] is False

    @pytest.mark.parametrize("bad", ["not-an-email", "a@b", "a b@example.com", "@example.com"])
    def test_rejects_malformed_addresses(self, client, bad):
        res = client.post("/auth/register", json={
            "username": "bob", "password": "correct-horse", "email": bad,
        })
        assert res.status_code == 400
        assert "email" in res.json["msg"]

    def test_duplicate_email_is_a_conflict(self, client):
        payload = {"password": "correct-horse", "email": "taken@example.com"}
        assert client.post("/auth/register", json={"username": "first", **payload}).status_code == 201
        res = client.post("/auth/register", json={"username": "second", **payload})
        assert res.status_code == 409
        assert "email" in res.json["msg"].lower()

    def test_me_reports_a_masked_address(self, client, user_with_email):
        client.post("/auth/login", json={"username": user_with_email, "password": "correct-horse"})
        body = client.get("/auth/me").json
        assert body["has_email"] is True
        # Stored lowercased, so the mask is too.
        assert body["email"] == "a***e@example.com"
        assert "alice@example.com" not in body["email"]


class TestForgotPassword:
    def test_issues_a_token_in_development(self, client, user_with_email):
        res = _reset(client)
        assert res.status_code == 202
        assert res.json["dev_token"]

    def test_does_not_reveal_a_missing_account(self, client, user_with_email):
        known = _reset(client)
        unknown = _reset(client, "nobody@example.com")

        # Identical shape and status, or this endpoint enumerates users.
        assert unknown.status_code == known.status_code == 202
        assert "dev_token" not in unknown.json
        assert unknown.json["msg"] == known.json["msg"]

    def test_address_matching_is_case_insensitive(self, client, user_with_email):
        assert _reset(client, "ALICE@EXAMPLE.COM").status_code == 202

    def test_blank_address_is_accepted_quietly(self, client):
        res = client.post("/auth/forgot-password", json={})
        assert res.status_code == 202

    def test_second_request_replaces_the_first_token(self, client, user_with_email, app):
        first = _reset(client).json["dev_token"]
        second = _reset(client).json["dev_token"]
        assert first != second

        with app.app_context():
            user = User.query.filter_by(username=user_with_email).one()
            # Only the newest token may work.
            assert user.matches_reset_token(second)
            assert not user.matches_reset_token(first)

    def test_no_raw_token_is_persisted(self, client, user_with_email, app):
        raw = _reset(client).json["dev_token"]
        with app.app_context():
            user = User.query.filter_by(username=user_with_email).one()
            assert user.password_reset_token_hash != raw


class TestResetPassword:
    def test_changes_the_password(self, client, user_with_email):
        token = _reset(client).json["dev_token"]
        res = client.post("/auth/reset-password", json={"token": token, "password": "new-password-1"})
        assert res.status_code == 200

        # The new password works, the old one does not.
        assert client.post("/auth/login", json={
            "username": user_with_email, "password": "new-password-1",
        }).status_code == 200
        assert client.post("/auth/login", json={
            "username": user_with_email, "password": "correct-horse",
        }).status_code == 401

    def test_token_is_single_use(self, client, user_with_email):
        token = _reset(client).json["dev_token"]
        payload = {"token": token, "password": "new-password-1"}
        assert client.post("/auth/reset-password", json=payload).status_code == 200

        replay = client.post("/auth/reset-password", json={**payload, "password": "another-one-1"})
        assert replay.status_code == 400
        assert "invalid or has expired" in replay.json["msg"]

    def test_rejects_a_wrong_token(self, client, user_with_email):
        _reset(client)
        other, _ = generate_token()
        res = client.post("/auth/reset-password", json={"token": other, "password": "new-password-1"})
        assert res.status_code == 400

    def test_rejects_an_expired_token(self, client, user_with_email, app):
        raw = _reset(client).json["dev_token"]
        with app.app_context():
            user = User.query.filter_by(username=user_with_email).one()
            user.password_reset_sent_at = datetime.now(UTC) - TOKEN_TTL - timedelta(minutes=1)
            db_session_commit(app)

        res = client.post("/auth/reset-password", json={"token": raw, "password": "new-password-1"})
        assert res.status_code == 400

    def test_expired_and_wrong_tokens_are_indistinguishable(self, client, user_with_email, app):
        raw = _reset(client).json["dev_token"]
        other, _ = generate_token()
        wrong = client.post("/auth/reset-password", json={"token": other, "password": "new-password-1"})

        with app.app_context():
            user = User.query.filter_by(username=user_with_email).one()
            user.password_reset_sent_at = datetime.now(UTC) - TOKEN_TTL - timedelta(minutes=1)
            db_session_commit(app)

        expired = client.post("/auth/reset-password", json={"token": raw, "password": "new-password-1"})
        assert expired.json["msg"] == wrong.json["msg"]

    def test_clears_the_session_cookies(self, client, user_with_email):
        token = _reset(client).json["dev_token"]
        res = client.post("/auth/reset-password", json={"token": token, "password": "new-password-1"})
        cleared = " ".join(res.headers.getlist("Set-Cookie"))
        assert "access_token_cookie" in cleared

    @pytest.mark.parametrize("missing", [{"token": ""}, {"token": None}, {}])
    def test_requires_a_token(self, client, missing):
        res = client.post("/auth/reset-password", json={**missing, "password": "new-password-1"})
        assert res.status_code == 400

    def test_enforces_password_rules(self, client, user_with_email):
        token = _reset(client).json["dev_token"]
        res = client.post("/auth/reset-password", json={"token": token, "password": "short"})
        assert res.status_code == 400
        assert "at least" in res.json["msg"]

        # The token survives a validation failure, so the user can retry.
        assert client.post("/auth/reset-password", json={
            "token": token, "password": "long-enough-password",
        }).status_code == 200

    def test_failed_reset_leaves_the_old_password_working(self, client, user_with_email):
        _reset(client)
        client.post("/auth/reset-password", json={"token": "nope", "password": "new-password-1"})
        assert client.post("/auth/login", json={
            "username": user_with_email, "password": "correct-horse",
        }).status_code == 200


def db_session_commit(app):
    from extensions import db

    db.session.commit()
