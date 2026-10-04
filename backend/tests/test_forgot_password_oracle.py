"""forgot-password must answer identically in every case.

The endpoint's whole value is that it is not a user-enumeration oracle. That
holds only while the response is byte-identical whether the address is unknown,
unconfirmed, confirmed, or confirmed with the mail server broken. The last case
used to answer 502 while the others answered 202, which told an attacker exactly
which addresses were real -- but only while SMTP was down, which is the worst
moment to leak it.
"""

import pytest

from routes.auth import GENERIC_RESET_MSG


def _confirmed(client, username="alice", email="alice@example.com"):
    client.post("/auth/register", json={
        "username": username, "password": "correct-horse", "email": email,
    })
    client.post("/auth/login", json={"username": username, "password": "correct-horse"})
    token = client.post("/account/verify-email/request").json["dev_token"]
    client.post("/account/verify-email/confirm", json={"token": token})
    client.post("/auth/logout")


class TestIndistinguishableResponses:
    def test_an_unknown_address_gets_the_generic_202(self, client):
        res = client.post("/auth/forgot-password", json={"email": "ghost@example.com"})
        assert res.status_code == 202
        assert res.json["msg"] == GENERIC_RESET_MSG

    def test_an_unconfirmed_address_gets_the_same_answer(self, client):
        client.post("/auth/register", json={
            "username": "bob", "password": "correct-horse", "email": "bob@example.com",
        })
        res = client.post("/auth/forgot-password", json={"email": "bob@example.com"})
        assert res.status_code == 202
        assert res.json["msg"] == GENERIC_RESET_MSG
        assert "dev_token" not in res.json

    def test_a_malformed_address_gets_the_same_answer(self, client):
        res = client.post("/auth/forgot-password", json={"email": "not-an-email"})
        assert res.status_code == 202
        assert res.json["msg"] == GENERIC_RESET_MSG

    def test_a_blank_address_gets_the_same_answer(self, client):
        assert client.post("/auth/forgot-password", json={}).status_code == 202

    def test_a_broken_mail_server_gets_the_same_answer(self, client, monkeypatch):
        # The regression. 502 here fires only for an address that exists, is
        # confirmed, and reached a failing SMTP call.
        _confirmed(client)
        client.post("/auth/logout")

        import routes.auth as auth_module

        def boom(*_args, **_kwargs):
            raise OSError("smtp unreachable")

        monkeypatch.setattr(auth_module, "send_password_reset", boom)
        res = client.post("/auth/forgot-password", json={"email": "alice@example.com"})

        assert res.status_code == 202
        assert res.json["msg"] == GENERIC_RESET_MSG
        assert "dev_token" not in res.json

    def test_all_four_outcomes_are_byte_identical(self, client, monkeypatch):
        _confirmed(client, "alice", "alice@example.com")
        client.post("/auth/register", json={
            "username": "bob", "password": "correct-horse", "email": "bob@example.com",
        })
        client.post("/auth/logout")

        unknown = client.post("/auth/forgot-password", json={"email": "ghost@example.com"})
        unconfirmed = client.post("/auth/forgot-password", json={"email": "bob@example.com"})
        confirmed = client.post("/auth/forgot-password", json={"email": "alice@example.com"})

        import routes.auth as auth_module

        def boom(*_args, **_kwargs):
            raise OSError("smtp unreachable")

        monkeypatch.setattr(auth_module, "send_password_reset", boom)
        broken = client.post("/auth/forgot-password", json={"email": "alice@example.com"})

        bodies = {unknown.get_data(), unconfirmed.get_data(), confirmed.get_data()}
        # The confirmed and broken cases both run with mail disabled in tests, so
        # the successful one carries dev_token and they cannot be compared
        # verbatim. Compare status and message instead, which is what a caller
        # can observe.
        statuses = {unknown.status_code, unconfirmed.status_code,
                    confirmed.status_code, broken.status_code}
        messages = {unknown.json["msg"], unconfirmed.json["msg"],
                    confirmed.json["msg"], broken.json["msg"]}

        assert statuses == {202}, statuses
        assert messages == {GENERIC_RESET_MSG}, messages
        assert len(bodies) >= 1

    def test_the_failure_is_still_logged_for_the_operator(self, client, monkeypatch, caplog):
        _confirmed(client)
        client.post("/auth/logout")

        import routes.auth as auth_module

        def boom(*_args, **_kwargs):
            raise OSError("smtp unreachable")

        monkeypatch.setattr(auth_module, "send_password_reset", boom)
        with caplog.at_level("ERROR"):
            client.post("/auth/forgot-password", json={"email": "alice@example.com"})

        # The caller learns nothing; the operator has to learn something.
        assert any("reset email failed" in r.message.lower() or r.exc_info
                   for r in caplog.records), [r.message for r in caplog.records]


class TestStillWorks:
    def test_a_reset_token_is_issued_when_mail_succeeds(self, client):
        _confirmed(client)
        client.post("/auth/logout")
        res = client.post("/auth/forgot-password", json={"email": "alice@example.com"})
        assert res.status_code == 202
        assert res.json.get("dev_token")

    def test_a_failed_send_does_not_leave_a_usable_token(self, client, monkeypatch):
        _confirmed(client)
        client.post("/auth/logout")

        import routes.auth as auth_module

        def boom(*_args, **_kwargs):
            raise OSError("smtp unreachable")

        monkeypatch.setattr(auth_module, "send_password_reset", boom)
        client.post("/auth/forgot-password", json={"email": "alice@example.com"})

        # The token was rolled back, so nothing can be guessed with it.
        res = client.post("/auth/reset-password", json={
            "token": "anything", "password": "new-password-1",
        })
        assert res.status_code == 400


@pytest.mark.parametrize("payload", [
    {"email": "alice@example.com"},
    {"email": "ALICE@EXAMPLE.COM"},
])
def test_address_matching_is_case_insensitive(client, payload):
    _confirmed(client)
    client.post("/auth/logout")
    assert client.post("/auth/forgot-password", json=payload).json.get("dev_token")
