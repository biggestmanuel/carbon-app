"""Password reset over HTTP.

Reset requires a *confirmed* address. That is the whole point: mailing an
unverified address would hand a reset link to whoever actually owns the inbox.
So these tests cover both the unverified refusal and the verified happy path.

Three further properties matter:
  1. /auth/forgot-password must not reveal whether an address exists, or
     whether it is verified.
  2. A token must work exactly once, and expire.
  3. An unverified address must be indistinguishable from an unknown one.
"""

from datetime import UTC, datetime, timedelta

import pytest

from models import User
from passwords import TOKEN_TTL, generate_token


def _register(client, username="alice", email=None, password="correct-horse"):
    payload = {"username": username, "password": password}
    if email:
        payload["email"] = email
    return client.post("/auth/register", json=payload)


def _confirm(client, email):
    """Walk the verification flow and return the confirmation token."""
    client.post("/auth/login", json={"username": "alice", "password": "correct-horse"})
    token = client.post("/account/verify-email/request").json["dev_token"]
    client.post("/account/verify-email/confirm", json={"token": token})
    client.post("/auth/logout")
    return token


@pytest.fixture
def verified_user(client):
    """alice, registered with an address and confirmed."""
    _register(client, "alice", "alice@example.com")
    _confirm(client, "alice@example.com")
    return "alice"


def _reset(client, address="alice@example.com"):
    return client.post("/auth/forgot-password", json={"email": address})


class TestRegistrationEmail:
    def test_accepts_and_normalises_an_email(self, client):
        res = _register(client, "bob", "Bob@Example.COM")
        assert res.status_code == 201
        assert res.json["verification_required"] is True
        # Not confirmed yet, so reset must not claim to be available.
        assert res.json["can_reset_password"] is False
        assert res.json["email_verified"] is False

    def test_email_is_optional(self, client):
        res = _register(client, "bob")
        assert res.status_code == 201
        assert res.json["can_reset_password"] is False
        assert res.json["verification_required"] is False

    @pytest.mark.parametrize("bad", ["not-an-email", "a@b", "a b@example.com", "@example.com"])
    def test_rejects_malformed_addresses(self, client, bad):
        res = _register(client, "bob", bad)
        assert res.status_code == 400
        assert "email" in res.json["msg"]

    def test_duplicate_email_is_a_conflict(self, client):
        _register(client, "first", "taken@example.com")
        res = _register(client, "second", "taken@example.com")
        assert res.status_code == 409
        assert "email" in res.json["msg"].lower()

    def test_me_reports_a_masked_unverified_address(self, client):
        _register(client, "alice", "Alice@Example.com")
        client.post("/auth/login", json={"username": "alice", "password": "correct-horse"})
        body = client.get("/auth/me").json
        assert body["has_email"] is True
        assert body["email"] == "a***e@example.com"
        assert body["email_verified"] is False

    def test_a_confirmation_failure_does_not_lose_the_account(self, client, app, monkeypatch):
        # The address must not be trusted, but the account still exists and can
        # still be used; verification can be retried later.
        import routes.auth as auth_module

        def boom(*_args, **_kwargs):
            raise RuntimeError("smtp down")

        monkeypatch.setattr(auth_module, "send_verification", boom)
        res = _register(client, "alice", "alice@example.com")
        assert res.status_code == 201

        client.post("/auth/login", json={"username": "alice", "password": "correct-horse"})
        assert client.get("/auth/me").status_code == 200
        assert client.get("/auth/me").json["email_verified"] is False


class TestForgotPassword:
    def test_issues_a_token_once_the_address_is_confirmed(self, client, verified_user):
        res = _reset(client)
        assert res.status_code == 202
        assert res.json["dev_token"]

    def test_refuses_an_unverified_address(self, client):
        _register(client, "alice", "alice@example.com")
        res = _reset(client)
        # Same shape and status as a known-and-confirmed account: returning a
        # different response here would leak which addresses are verified.
        assert res.status_code == 202
        assert "dev_token" not in res.json
        assert res.json["msg"] == "If that address exists, a reset link is on its way."

    def test_unverified_unknown_and_verified_are_indistinguishable(self, client, app):
        _register(client, "alice", "alice@example.com")  # registered, unverified
        unverified = _reset(client, "alice@example.com")
        unknown = _reset(client, "ghost@example.com")

        assert unknown.status_code == unverified.status_code == 202
        assert unknown.json["msg"] == unverified.json["msg"]
        assert "dev_token" not in unknown.json
        assert "dev_token" not in unverified.json

    def test_does_not_reveal_a_missing_account(self, client, verified_user):
        known = _reset(client)
        unknown = _reset(client, "nobody@example.com")
        assert unknown.status_code == known.status_code == 202
        assert unknown.json["msg"] == known.json["msg"]
        assert "dev_token" not in unknown.json

    def test_address_matching_is_case_insensitive(self, client, verified_user):
        assert _reset(client, "ALICE@EXAMPLE.COM").json.get("dev_token")

    def test_blank_address_is_accepted_quietly(self, client):
        assert client.post("/auth/forgot-password", json={}).status_code == 202

    def test_second_request_replaces_the_first_token(self, client, verified_user, app):
        first = _reset(client).json["dev_token"]
        second = _reset(client).json["dev_token"]
        assert first != second
        with app.app_context():
            user = User.query.filter_by(username="alice").one()
            assert user.matches_reset_token(second)
            assert not user.matches_reset_token(first)

    def test_no_raw_token_is_persisted(self, client, verified_user, app):
        raw = _reset(client).json["dev_token"]
        with app.app_context():
            user = User.query.filter_by(username="alice").one()
            assert user.password_reset_token_hash != raw


class TestResetPassword:
    def test_changes_the_password(self, client, verified_user):
        token = _reset(client).json["dev_token"]
        res = client.post("/auth/reset-password", json={"token": token, "password": "new-password-1"})
        assert res.status_code == 200

        assert client.post("/auth/login", json={
            "username": "alice", "password": "new-password-1",
        }).status_code == 200
        assert client.post("/auth/login", json={
            "username": "alice", "password": "correct-horse",
        }).status_code == 401

    def test_token_is_single_use(self, client, verified_user):
        token = _reset(client).json["dev_token"]
        payload = {"token": token, "password": "new-password-1"}
        assert client.post("/auth/reset-password", json=payload).status_code == 200

        replay = client.post("/auth/reset-password", json={**payload, "password": "another-one-1"})
        assert replay.status_code == 400
        assert "invalid or has expired" in replay.json["msg"]

    def test_rejects_a_wrong_token(self, client, verified_user):
        _reset(client)
        other, _ = generate_token()
        res = client.post("/auth/reset-password", json={"token": other, "password": "new-password-1"})
        assert res.status_code == 400

    def test_rejects_an_expired_token(self, client, verified_user, app):
        raw = _reset(client).json["dev_token"]
        with app.app_context():
            user = User.query.filter_by(username="alice").one()
            user.password_reset_sent_at = datetime.now(UTC) - TOKEN_TTL - timedelta(minutes=1)
            db_session_commit(app)

        res = client.post("/auth/reset-password", json={"token": raw, "password": "new-password-1"})
        assert res.status_code == 400

    def test_expired_and_wrong_tokens_are_indistinguishable(self, client, verified_user, app):
        raw = _reset(client).json["dev_token"]
        other, _ = generate_token()
        wrong = client.post("/auth/reset-password", json={"token": other, "password": "new-password-1"})

        with app.app_context():
            user = User.query.filter_by(username="alice").one()
            user.password_reset_sent_at = datetime.now(UTC) - TOKEN_TTL - timedelta(minutes=1)
            db_session_commit(app)

        expired = client.post("/auth/reset-password", json={"token": raw, "password": "new-password-1"})
        assert expired.json["msg"] == wrong.json["msg"]

    def test_clears_the_session_cookies(self, client, verified_user):
        token = _reset(client).json["dev_token"]
        res = client.post("/auth/reset-password", json={"token": token, "password": "new-password-1"})
        cleared = " ".join(res.headers.getlist("Set-Cookie"))
        assert "access_token_cookie" in cleared

    @pytest.mark.parametrize("missing", [{"token": ""}, {"token": None}, {}])
    def test_requires_a_token(self, client, missing):
        res = client.post("/auth/reset-password", json={**missing, "password": "new-password-1"})
        assert res.status_code == 400

    def test_enforces_password_rules(self, client, verified_user):
        token = _reset(client).json["dev_token"]
        res = client.post("/auth/reset-password", json={"token": token, "password": "short"})
        assert res.status_code == 400
        assert "at least" in res.json["msg"]

        # The token survives a validation failure, so the user can retry.
        assert client.post("/auth/reset-password", json={
            "token": token, "password": "long-enough-password",
        }).status_code == 200

    def test_failed_reset_leaves_the_old_password_working(self, client, verified_user):
        _reset(client)
        client.post("/auth/reset-password", json={"token": "nope", "password": "new-password-1"})
        assert client.post("/auth/login", json={
            "username": "alice", "password": "correct-horse",
        }).status_code == 200


def db_session_commit(app):
    from extensions import db

    db.session.commit()
