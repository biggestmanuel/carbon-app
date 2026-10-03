"""Account lifecycle: verification, sessions, export, deletion.

These endpoints cover the rights a user is normally expected to have: prove
they own an address, see and end individual sessions, take their data, and leave.
"""

import csv
import io
import json

import pytest

from models import Footprint, User, UserSession


def _register(client, username="alice", password="correct-horse", email=None):
    payload = {"username": username, "password": password}
    if email:
        payload["email"] = email
    return client.post("/auth/register", json=payload)


def _login(client, username="alice", password="correct-horse"):
    # Register on demand so each test can start from whichever state it needs.
    _register(client, username, password=password)
    res = client.post("/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.get_json()
    return res


@pytest.fixture
def confirmed(client):
    """alice with a confirmed address."""
    _register(client, "alice", email="alice@example.com")
    _login(client)
    token = client.post("/account/verify-email/request").json["dev_token"]
    client.post("/account/verify-email/confirm", json={"token": token})
    return "alice"


class TestVerificationRequest:
    def test_requires_a_session(self, client):
        _register(client, "alice", email="alice@example.com")
        assert client.post("/account/verify-email/request").status_code == 401

    def test_issues_a_token_for_a_pending_address(self, client):
        _register(client, "alice", email="alice@example.com")
        _login(client)
        res = client.post("/account/verify-email/request")
        assert res.status_code == 202
        assert res.json["dev_token"]

    def test_refuses_when_there_is_no_address(self, client):
        _register(client, "alice")
        _login(client)
        res = client.post("/account/verify-email/request")
        assert res.status_code == 400
        assert "no email address" in res.json["msg"]

    def test_is_idempotent_once_confirmed(self, client, confirmed):
        res = client.post("/account/verify-email/request")
        assert res.status_code == 200
        assert "already confirmed" in res.json["msg"]


class TestVerificationConfirm:
    def test_marks_the_address_verified(self, client):
        _register(client, "alice", email="alice@example.com")
        _login(client)
        token = client.post("/account/verify-email/request").json["dev_token"]

        res = client.post("/account/verify-email/confirm", json={"token": token})
        assert res.status_code == 200
        assert res.json["email_verified"] is True
        assert client.get("/auth/me").json["email_verified"] is True

    def test_token_is_single_use(self, client):
        _register(client, "alice", email="alice@example.com")
        _login(client)
        token = client.post("/account/verify-email/request").json["dev_token"]

        assert client.post("/account/verify-email/confirm", json={"token": token}).status_code == 200
        # A second click on the same link must not silently succeed.
        assert client.post("/account/verify-email/confirm", json={"token": token}).status_code == 400

    def test_rejects_a_wrong_token(self, client):
        _register(client, "alice", email="alice@example.com")
        _login(client)
        res = client.post("/account/verify-email/confirm", json={"token": "not-a-token"})
        assert res.status_code == 400

    @pytest.mark.parametrize("missing", [{"token": ""}, {"token": None}, {}])
    def test_requires_a_token(self, client, missing):
        assert client.post("/account/verify-email/confirm", json=missing).status_code == 400

    def test_confirming_unlocks_password_reset(self, client):
        _register(client, "alice", email="alice@example.com")
        _login(client)
        token = client.post("/account/verify-email/request").json["dev_token"]
        client.post("/account/verify-email/confirm", json={"token": token})

        res = client.post("/auth/forgot-password", json={"email": "alice@example.com"})
        assert res.json.get("dev_token"), "a confirmed address should receive a reset token"


class TestSessions:
    def test_lists_the_current_session(self, client):
        _login(client)
        body = client.get("/account/sessions").json
        assert len(body["sessions"]) == 1
        assert body["sessions"][0]["current"] is True
        assert body["sessions"][0]["label"]

    def test_each_login_creates_a_session(self, client):
        # Two logins from two "devices" without logging out in between.
        _login(client)
        _login(client)
        body = client.get("/account/sessions").json
        assert len(body["sessions"]) == 2
        assert sum(1 for s in body["sessions"] if s["current"]) == 1

    def test_logout_removes_only_that_device(self, client, app):
        _login(client)
        _login(client)
        assert len(client.get("/account/sessions").json["sessions"]) == 2
        doomed = next(
            s["id"] for s in client.get("/account/sessions").json["sessions"] if not s["current"]
        )

        client.post("/auth/logout")
        # This browser's cookies are gone, so check the stored rows instead: the
        # other device must still be there.
        assert client.get("/account/sessions").status_code == 401
        with app.app_context():
            remaining = UserSession.query.all()
            assert len(remaining) == 1
            assert remaining[0].id == doomed

    def test_revoking_the_current_session_signs_this_device_out(self, client):
        _login(client)
        session_id = client.get("/account/sessions").json["sessions"][0]["id"]

        res = client.delete(f"/account/sessions/{session_id}")
        assert res.status_code == 200
        assert res.json["was_current"] is True
        # Cookies were cleared, so the next call is unauthenticated.
        assert client.get("/account/sessions").status_code == 401

    def test_revoking_another_session_leaves_this_one_working(self, client):
        _login(client)
        _login(client)
        sessions = client.get("/account/sessions").json["sessions"]
        other = next(s["id"] for s in sessions if not s["current"])

        res = client.delete(f"/account/sessions/{other}")
        assert res.status_code == 200
        assert res.json["was_current"] is False
        assert client.get("/account/sessions").status_code == 200
        assert len(client.get("/account/sessions").json["sessions"]) == 1

    def test_cannot_revoke_another_users_session(self, client, app):
        _login(client, "alice")
        alice_session = client.get("/account/sessions").json["sessions"][0]["id"]

        # No logout here: it would delete alice's session, and the point is that
        # it still exists when bob tries to reach it.
        _register(client, "bob", password="another-password")
        client.post("/auth/login", json={"username": "bob", "password": "another-password"})
        # Scoping by user_id means a guessed UUID cannot revoke a stranger.
        res = client.delete(f"/account/sessions/{alice_session}")
        assert res.status_code == 404

        with app.app_context():
            assert db_session_exists(app, alice_session)

    def test_unknown_session_is_404(self, client):
        _login(client)
        assert client.delete("/account/sessions/does-not-exist").status_code == 404

    def test_sign_out_everywhere_ends_all_of_them(self, client):
        _login(client)
        _login(client)
        assert len(client.get("/account/sessions").json["sessions"]) == 2

        res = client.delete("/account/sessions")
        assert res.status_code == 200
        # Cleared this device's cookies too.
        assert client.get("/account/sessions").status_code == 401

    def test_a_revoked_session_token_stops_working(self, client, app):
        _login(client)
        session_id = client.get("/account/sessions").json["sessions"][0]["id"]

        # Revoke via a direct delete, then reuse the cookie that was issued for it.
        with app.app_context():
            session = db_session_get(app, session_id)
            db_session_delete(app, session)
            app.extensions["sqlalchemy"].session.commit()

        assert client.get("/auth/me").status_code == 401

    def test_session_rows_record_device_hints(self, client, app):
        _register(client, "alice")
        res = client.post(
            "/auth/login",
            json={"username": "alice", "password": "correct-horse"},
            headers={"User-Agent": "Mozilla/5.0 Chrome/120.0"},
        )
        assert res.status_code == 200
        with app.app_context():
            row = UserSession.query.one()
            assert row.user_agent and "Chrome" in row.user_agent
            assert row.ip_address


class TestExport:
    def _seed(self, client, count=3):
        _login(client)
        for km in range(count):
            client.post("/footprint/calculate", json={
                "car_km": km * 10, "electricity_kwh": 100,
                "meat_meals": 1, "plant_meals": 2,
            })

    def test_json_export_requires_a_session(self, client):
        assert client.get("/account/export").status_code == 401

    def test_json_export_contains_every_entry(self, client):
        self._seed(client, 3)
        res = client.get("/account/export")
        assert res.status_code == 200
        assert "attachment" in res.headers["Content-Disposition"]

        body = json.loads(res.data)
        assert body["entry_count"] == 3
        assert body["account"]["username"] == "alice"
        assert len(body["entries"]) == 3
        # Each entry carries the factor snapshot, so the export stays meaningful.
        assert body["entries"][0]["factors_applied"]

    def test_csv_export_parses(self, client):
        self._seed(client, 2)
        res = client.get("/account/export?format=csv")
        assert res.status_code == 200
        assert res.mimetype == "text/csv"

        rows = list(csv.DictReader(io.StringIO(res.data.decode())))
        assert len(rows) == 2
        assert rows[0]["region"] == "world"
        assert float(rows[0]["total_kg_co2e"]) > 0

    def test_export_is_scoped_to_the_caller(self, client):
        self._seed(client, 2)
        client.post("/auth/logout")

        _register(client, "bob", password="another-password")
        client.post("/auth/login", json={"username": "bob", "password": "another-password"})
        body = json.loads(client.get("/account/export").data)
        assert body["entry_count"] == 0


class TestDeletion:
    def test_requires_the_password_again(self, client):
        _login(client)
        res = client.delete("/account/account", json={"password": "wrong-password"})
        assert res.status_code == 403
        assert "incorrect" in res.json["msg"]
        # Still there.
        assert client.get("/auth/me").status_code == 200

    def test_requires_a_password_field(self, client):
        _login(client)
        assert client.delete("/account/account", json={}).status_code == 403

    def test_deletes_the_account_and_its_history(self, client, app):
        _login(client)
        client.post("/footprint/calculate", json={
            "car_km": 10, "electricity_kwh": 20, "meat_meals": 1, "plant_meals": 1,
        })

        res = client.delete("/account/account", json={"password": "correct-horse"})
        assert res.status_code == 200

        with app.app_context():
            assert User.query.count() == 0
            assert Footprint.query.count() == 0, "footprints must not outlive the account"
            assert UserSession.query.count() == 0, "sessions must not outlive the account"

    def test_clears_the_session(self, client):
        _login(client)
        res = client.delete("/account/account", json={"password": "correct-horse"})
        assert "access_token_cookie" in " ".join(res.headers.getlist("Set-Cookie"))
        assert client.get("/auth/me").status_code == 401

    def test_requires_a_session(self, client):
        res = client.delete("/account/account", json={"password": "correct-horse"})
        assert res.status_code == 401

    def test_a_stolen_cookie_is_not_enough(self, client):
        # The whole point of re-asking: a session cookie alone must not be able
        # to destroy someone's history.
        _login(client)
        assert client.delete("/account/account", json={"password": "guess-the-password"}).status_code == 403


# --- helpers -------------------------------------------------------------


def db_session_get(app, session_id):
    from extensions import db

    return db.session.get(UserSession, session_id)


def db_session_delete(app, session):
    from extensions import db

    db.session.delete(session)


def db_session_exists(app, session_id):
    from extensions import db

    return db.session.get(UserSession, session_id) is not None
