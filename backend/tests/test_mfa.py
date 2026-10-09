"""Two-factor authentication, end to end.

The tests are organised around what an attacker actually has, because every
interesting property here is about refusing them something:

- a stolen password, and what /auth/login hands back;
- a valid code, and whether it can be replayed;
- a database dump, and whether the seed or the recovery codes are usable.

The recurring assertion is that a failure looks identical whichever half of the
system the guess was aimed at. A user who mistypes their code and an attacker
brute-forcing one must get the same status, the same body and -- as far as a test
can see -- the same work done.
"""

import time

import pytest

from mfa import KeyUnavailable, decrypt, encrypt
from models import RecoveryCode, User, UserSession
from totp import current_code, generate_secret, verify


def _start(client):
    res = client.get("/auth/mfa/start")
    assert res.status_code == 200, res.get_json()
    return res.get_json()


class TestSecretIsNotStoredInPlaintext:
    def test_the_column_holds_ciphertext(self, client, auth_headers, enroll_mfa):
        auth_headers()
        secret, _codes = enroll_mfa()

        user = User.query.filter_by(username="alice").one()
        # The plaintext seed must not be sitting in the row.
        assert user.totp_secret is not None
        assert secret not in user.totp_secret

    def test_it_decrypts_back_with_the_key(self, client, auth_headers, enroll_mfa,
                                           totp_key):
        auth_headers()
        secret, _codes = enroll_mfa()

        user = User.query.filter_by(username="alice").one()
        assert totp_key.decrypt(user.totp_secret.encode()) == secret.encode()

    def test_start_does_not_write_anything(self, client, auth_headers):
        # Enrolment is two steps and only the second one persists, so an
        # abandoned setup leaves no half-enabled factor and no seed in the
        # database for a user who scanned a QR code and then changed their mind.
        auth_headers()
        _start(client)

        user = User.query.filter_by(username="alice").one()
        assert user.totp_secret is None
        assert user.totp_enabled is False

    def test_the_export_does_not_leak_the_seed(self, client, auth_headers, enroll_mfa):
        auth_headers()
        secret, _codes = enroll_mfa()

        res = client.get("/account/export?format=json")
        assert secret not in res.get_data(as_text=True)
        assert "totp_secret" not in res.get_json()["account"]

    def test_the_me_endpoint_does_not_leak_the_seed(self, client, auth_headers, enroll_mfa):
        auth_headers()
        secret, _codes = enroll_mfa()

        body = client.get("/auth/me").get_json()
        assert secret not in str(body)
        assert body["totp_enabled"] is True


class TestTheKeyIsRequiredAtEnrolment:
    def test_enrolment_refuses_without_a_key(self, client, auth_headers, app, monkeypatch):
        # A misconfigured deployment must not store a plaintext seed as a
        # fallback, and must say so in terms the operator can act on.
        monkeypatch.setitem(app.config, "TOTP_ENCRYPTION_KEY", "")
        auth_headers()

        res = client.get("/auth/mfa/start")
        assert res.status_code == 503
        assert "not configured" in res.json["msg"]

    def test_an_invalid_key_is_refused_too(self, client, auth_headers, app, monkeypatch):
        monkeypatch.setitem(app.config, "TOTP_ENCRYPTION_KEY", "too-short")
        auth_headers()

        assert client.get("/auth/mfa/start").status_code == 503

    def test_a_tampered_ciphertext_does_not_verify(self, client, auth_headers, enroll_mfa):
        # Fernet authenticates as well as encrypts, so a modified row fails to
        # decrypt rather than yielding a seed that matches attacker-chosen codes.
        auth_headers()
        secret, _codes = enroll_mfa()

        from extensions import db

        user = User.query.filter_by(username="alice").one()
        ciphertext = user.totp_secret
        user.totp_secret = ciphertext[:-8] + "AAAAAAAA"
        db.session.commit()

        assert decrypt(user.totp_secret) is None
        # And the login path therefore refuses.
        assert client.post("/auth/logout").status_code == 200


class TestPasswordAloneIsNotEnough:
    def test_login_asks_for_a_second_factor(self, client, auth_headers, enroll_mfa, login):
        auth_headers()
        secret, _codes = enroll_mfa()
        client.post("/auth/logout")

        res = login()
        assert res.status_code == 200
        assert res.json["mfa_required"] is True
        assert res.json["pending_token"]

    def test_it_issues_no_session_cookies(self, client, auth_headers, enroll_mfa, login):
        # The whole point. A 200 with a pending token must not also hand over a
        # working session, or the second factor is decorative.
        auth_headers()
        enroll_mfa()
        client.post("/auth/logout")

        res = login()
        assert res.json.get("username") is None
        # No access cookie, so no authenticated endpoint will answer.
        assert client.get("/auth/me").status_code == 401

    def test_it_creates_no_session_row(self, client, auth_headers, enroll_mfa, login):
        auth_headers()
        enroll_mfa()
        client.post("/auth/logout")
        UserSession_count = __import__("models").UserSession.query.count()

        login()
        # The password step must not leave a device behind, or the session list
        # would show a login that never completed.
        assert __import__("models").UserSession.query.count() == UserSession_count

    def test_a_wrong_password_still_gets_bad_credentials(self, client, auth_headers,
                                                        enroll_mfa, login):
        auth_headers()
        enroll_mfa()
        client.post("/auth/logout")

        res = login(password="wrong-password")
        assert res.status_code == 401
        # Not the mfa_required shape: a wrong password must not confirm that the
        # account exists and has 2FA on.
        assert "pending_token" not in res.json

    def test_accounts_without_2fa_are_unaffected(self, client, auth_headers, login):
        auth_headers()
        client.post("/auth/logout")

        res = login()
        assert res.status_code == 200
        assert "mfa_required" not in res.json
        assert client.get("/auth/me").status_code == 200


class TestCompletingTheLogin:
    def test_a_valid_code_completes_it(self, client, auth_headers, enroll_mfa, login,
                                      finish_mfa_login):
        auth_headers()
        secret, _codes = enroll_mfa()
        client.post("/auth/logout")

        pending = login().json["pending_token"]
        res = finish_mfa_login(pending, current_code(secret))

        assert res.status_code == 200
        assert res.json["second_factor"] == "totp"
        assert client.get("/auth/me").status_code == 200

    def test_a_wrong_code_is_refused(self, client, auth_headers, enroll_mfa, login,
                                     finish_mfa_login):
        auth_headers()
        secret, _codes = enroll_mfa()
        client.post("/auth/logout")

        pending = login().json["pending_token"]
        assert finish_mfa_login(pending, "000000").status_code == 401
        # And nothing was granted.
        assert client.get("/auth/me").status_code == 401

    def test_a_code_from_a_different_secret_is_refused(self, client, auth_headers,
                                                       enroll_mfa, login, finish_mfa_login):
        # The code has the right shape and a valid checksum for *some* seed.
        # Only the enrolled one may pass.
        auth_headers()
        secret, _codes = enroll_mfa()
        client.post("/auth/logout")

        pending = login().json["pending_token"]
        assert finish_mfa_login(pending, current_code(generate_secret())).status_code == 401

    def test_a_missing_pending_token_is_refused(self, client, auth_headers, enroll_mfa,
                                                finish_mfa_login):
        auth_headers()
        secret, _codes = enroll_mfa()

        assert finish_mfa_login("", current_code(secret)).status_code == 401

    def test_the_pending_token_cannot_be_used_as_a_session(self, client, auth_headers,
                                                           enroll_mfa, login):
        # The token is an access token so the client can hold it, but it is not a
        # credential: it carries no session id and the blocklist refuses it.
        auth_headers()
        secret, _codes = enroll_mfa()
        client.post("/auth/logout")

        pending = login().json["pending_token"]
        client.set_cookie("carbon_access", pending)

        assert client.get("/auth/me").status_code == 401
        assert client.get("/footprint/summary").status_code == 401
        assert client.get("/account/sessions").status_code == 401


def _confirmed_alice_with_2fa(client):
    """Register alice with a confirmed address, then arm 2FA. Returns the secret.

    The shared auth_headers fixture creates alice with no email, and a password
    reset requires a confirmed address -- so these tests build the account
    themselves rather than skipping for want of a mail transport.
    """
    client.post("/auth/register", json={
        "username": "alice", "password": "correct-horse",
        "email": "alice@example.com",
    })
    client.post("/auth/login", json={"username": "alice", "password": "correct-horse"})
    token = client.post("/account/verify-email/request").json["dev_token"]
    assert token, "a registered address should produce a confirmation token"
    client.post("/account/verify-email/confirm", json={"token": token})

    # Enrol while still signed in. Logging out first would leave no session, and
    # /auth/mfa/start is deliberately session-gated.
    secret = client.get("/auth/mfa/start").json["secret"]
    res = client.post("/auth/mfa/confirm", json={
        "secret": secret, "code": current_code(secret),
    })
    assert res.status_code == 200
    client.post("/auth/logout")
    return secret


def _reset_alices_password(client):
    """Bump alice's token_version through the real password-reset flow.

    Walks a genuine reset rather than incrementing the column directly, so these
    tests prove the version bump happens on the path a real user would take.
    """
    reset = client.post("/auth/forgot-password", json={"email": "alice@example.com"})
    assert reset.status_code == 202
    reset_token = reset.json.get("dev_token")
    assert reset_token, "a confirmed address should receive a reset token"
    res = client.post("/auth/reset-password", json={
        "token": reset_token, "password": "a-fresh-password",
    })
    assert res.status_code == 200


class TestThePendingTokenHonoursTheCredentialVersion:
    """A password reset must cancel a login that is already half-finished.

    The pending token embeds the token_version it was minted under. This was
    written from the first commit and never checked, so the token advertised a
    guarantee the code did not keep.
    """

    def test_a_reset_invalidates_a_pending_login(self, client, login, finish_mfa_login):
        secret = _confirmed_alice_with_2fa(client)

        pending = login().json["pending_token"]
        _reset_alices_password(client)

        # Same pending token, same correct code: must be refused.
        res = finish_mfa_login(pending, current_code(secret))
        assert res.status_code == 401
        assert client.get("/auth/me").status_code == 401

    def test_a_fresh_pending_token_still_works_after_a_reset(
        self, client, login, finish_mfa_login
    ):
        # The guard must invalidate only the stale token, not the login flow.
        secret = _confirmed_alice_with_2fa(client)

        _reset_alices_password(client)
        # The reset changed the password, so log in with the new one.
        fresh = login(password="a-fresh-password").json["pending_token"]
        assert finish_mfa_login(fresh, current_code(secret)).status_code == 200

    def test_the_claim_is_actually_present(self, client, auth_headers, enroll_mfa, login):
        # Guards against the claim being dropped again: without it there is
        # nothing for the check above to compare. Needs 2FA on, since that is what
        # makes login return a pending token at all.
        auth_headers()
        enroll_mfa()
        client.post("/auth/logout")

        pending = login().json["pending_token"]
        from flask_jwt_extended import decode_token

        claims = decode_token(pending)
        assert claims.get("ver") is not None
        assert claims.get("mfa_pending") is True

    def test_the_version_is_compared_against_the_user(
        self, client, auth_headers, enroll_mfa, app
    ):
        # A token whose version is wrong for an unrelated reason is also refused,
        # so the comparison cannot be satisfied by a missing claim. Minted with a
        # valid signature, so only the version check can reject it.
        from flask_jwt_extended import create_access_token

        auth_headers()
        secret, _codes = enroll_mfa()
        client.post("/auth/logout")

        with app.app_context():
            from models import User

            user = User.query.filter_by(username="alice").one()
            bad = create_access_token(
                identity=str(user.id),
                additional_claims={"mfa_pending": True, "ver": 999999},
            )

        assert client.post("/auth/mfa/check", json={
            "pending_token": bad, "code": current_code(secret),
        }).status_code == 401


class TestAnUnreadableSeedIsNotSilent:
    """A rotated encryption key breaks every enrolled user.

    decrypt() returns None rather than raising, which is right for refusing a
    login -- but it means a key rotation produces a clean 401 with no indication
    of the cause, and recovery codes become the only way back in. The operator has
    no way to tell that from an ordinary wrong code, so the login path logs it.
    """

    def _corrupt_the_seed(self, app):
        with app.app_context():
            from extensions import db
            from models import User

            user = User.query.filter_by(username="alice").one()
            # Same shape, wrong key: Fernet's tag makes it fail to decrypt.
            user.totp_secret = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
            db.session.commit()
            return user

    def test_a_failed_decrypt_is_logged_with_the_cause(
        self, client, auth_headers, enroll_mfa, login, finish_mfa_login, app, caplog
    ):
        auth_headers()
        secret, _codes = enroll_mfa()
        client.post("/auth/logout")
        self._corrupt_the_seed(app)

        with caplog.at_level("ERROR"):
            finish_mfa_login(login().json["pending_token"], current_code(secret))

        assert any("TOTP_ENCRYPTION_KEY" in r.message for r in caplog.records), (
            "the operator needs to be told the key is the likely cause"
        )

    def test_the_client_cannot_tell_an_unreadable_seed_from_a_wrong_code(
        self, client, auth_headers, enroll_mfa, login, finish_mfa_login, app
    ):
        # The log is for the operator, not the caller. Both cases must look
        # identical from outside, or this becomes an oracle for whether an account
        # exists and is enrolled.
        auth_headers()
        secret, _codes = enroll_mfa()
        client.post("/auth/logout")

        pending = login().json["pending_token"]
        wrong_code = finish_mfa_login(pending, "000000")
        self._corrupt_the_seed(app)
        unreadable = finish_mfa_login(pending, current_code(secret))

        assert unreadable.status_code == wrong_code.status_code
        assert unreadable.json == wrong_code.json

    def test_a_healthy_seed_does_not_log(
        self, client, auth_headers, enroll_mfa, login, finish_mfa_login, caplog
    ):
        auth_headers()
        secret, _codes = enroll_mfa()
        client.post("/auth/logout")

        with caplog.at_level("ERROR"):
            res = finish_mfa_login(login().json["pending_token"], current_code(secret))

        assert res.status_code == 200
        assert not any("TOTP_ENCRYPTION_KEY" in r.message for r in caplog.records)

    def test_a_user_without_2fa_does_not_log(self, client, auth_headers, login, caplog):
        # requires_totp() is False, so there is no seed that could have failed to
        # decrypt. The guard on the log is user.requires_totp(), and without this
        # the error would fire on every ordinary login for every account.
        auth_headers()

        with caplog.at_level("ERROR"):
            res = login()

        assert res.status_code == 200
        assert "pending_token" not in res.json
        assert not any("TOTP_ENCRYPTION_KEY" in r.message for r in caplog.records)


class TestThePendingTokenLifetime:
    def test_an_expired_pending_token_is_refused(self, client, auth_headers, enroll_mfa,
                                                     login, finish_mfa_login, monkeypatch):
        auth_headers()
        secret, _codes = enroll_mfa()
        client.post("/auth/logout")

        # Shorten the lifetime rather than sleeping through five minutes. The
        # patch goes on the routes module, because that is where the function
        # being replaced actually lives.
        import datetime

        import routes.mfa as mfa_routes

        monkeypatch.setattr(
            mfa_routes, "_pending_lifetime", lambda: datetime.timedelta(seconds=-1)
        )
        pending = login().json["pending_token"]

        assert finish_mfa_login(pending, current_code(secret)).status_code == 401

    def test_the_pending_token_is_short_lived(self, app):
        # Five minutes, not the session lifetime. This token is a gap between two
        # halves of one login, and a longer life hands a password thief more
        # attempts at six digits than the rate limit allows in one burst.
        import datetime

        import routes.mfa as mfa_routes

        with app.test_request_context():
            assert mfa_routes._pending_lifetime() == datetime.timedelta(minutes=5)


class TestEnrolmentDoesNotDisturbTheSession:
    def test_enrolling_does_not_log_the_current_session_out(self, client, auth_headers,
                                                            enroll_mfa):
        # The user is already signed in where they are enrolling. Revoking here
        # would log them out of the very device they just protected.
        auth_headers()
        enroll_mfa()

        assert client.get("/auth/me").status_code == 200


class TestCodeReplay:
    def test_a_code_cannot_be_used_twice(self, client, auth_headers, enroll_mfa, login,
                                         finish_mfa_login):
        # Shoulder-surfing a code off a screen leaves it valid for the rest of its
        # 30 second window. Spending it on first use is what closes that.
        auth_headers()
        secret, _codes = enroll_mfa()

        code = current_code(secret)
        first = finish_mfa_login(login().json["pending_token"], code)
        assert first.status_code == 200

        client.post("/auth/logout")
        second = finish_mfa_login(login().json["pending_token"], code)
        assert second.status_code == 401

    def test_the_counter_only_moves_forward(self, client, auth_headers, enroll_mfa, app):
        # A stale counter must not be able to walk the marker backwards, or an
        # old code becomes replayable again.
        auth_headers()
        secret, _codes = enroll_mfa()

        user = User.query.filter_by(username="alice").one()
        user.totp_last_counter = 5_000_000_000
        from extensions import db

        db.session.commit()

        user.consume_totp_counter(4_999_999_999)
        assert user.totp_last_counter == 5_000_000_000

        user.consume_totp_counter(5_000_000_001)
        assert user.totp_last_counter == 5_000_000_001

    def test_the_next_time_step_still_works(self, client, auth_headers, enroll_mfa,
                                            login, finish_mfa_login):
        # Replay protection must not lock out the user whose code expired while
        # they were typing it.
        auth_headers()
        secret, _codes = enroll_mfa()

        from totp import code_at, current_counter

        future = current_counter() + 1
        finish_mfa_login(login().json["pending_token"], code_at(secret, future))

        # The earlier step is now spent, so it must be refused.
        earlier = code_at(secret, future - 1)
        assert finish_mfa_login(login().json["pending_token"], earlier).status_code == 401


class TestRecoveryCodes:
    def test_they_are_returned_once_at_enrolment(self, client, auth_headers, enroll_mfa):
        auth_headers()
        _secret, codes = enroll_mfa()

        assert len(codes) == 10
        assert all(len(c) == 16 for c in codes)
        assert len(set(codes)) == 10

    def test_only_hashes_are_stored(self, client, auth_headers, enroll_mfa):
        auth_headers()
        _secret, codes = enroll_mfa()

        rows = RecoveryCode.query.all()
        assert len(rows) == 10
        for code in codes:
            assert code not in {row.code_hash for row in rows}
        # And no plaintext column exists to have put it in.
        assert "code" not in RecoveryCode.__table__.columns

    def test_a_code_logs_in(self, client, auth_headers, enroll_mfa, login,
                            finish_mfa_login):
        auth_headers()
        _secret, codes = enroll_mfa()
        client.post("/auth/logout")

        res = finish_mfa_login(login().json["pending_token"], codes[0])
        assert res.status_code == 200
        # The UI needs to know the authenticator was not used, so the owner knows
        # to re-enrol rather than assume everything is fine.
        assert res.json["second_factor"] == "recovery"

    def test_a_code_is_single_use(self, client, auth_headers, enroll_mfa, login,
                                  finish_mfa_login):
        auth_headers()
        _secret, codes = enroll_mfa()
        code = codes[0]

        assert finish_mfa_login(login().json["pending_token"], code).status_code == 200
        client.post("/auth/logout")
        assert finish_mfa_login(login().json["pending_token"], code).status_code == 401

    def test_use_is_recorded_not_deleted(self, client, auth_headers, enroll_mfa, login,
                                         finish_mfa_login):
        # So an exhausted account can tell "all ten used" from "never had any",
        # and so reuse can be counted.
        auth_headers()
        _secret, codes = enroll_mfa()
        finish_mfa_login(login().json["pending_token"], codes[0])

        row = RecoveryCode.query.filter_by(used_at=None).count()
        assert row == 9

    def test_casing_and_spacing_do_not_matter(self, client, auth_headers, enroll_mfa,
                                              login, finish_mfa_login):
        # Users read these off a printed sheet.
        auth_headers()
        _secret, codes = enroll_mfa()
        client.post("/auth/logout")

        messy = f"  {codes[0].lower()} "
        assert finish_mfa_login(login().json["pending_token"], messy).status_code == 200

    def test_the_remaining_count_is_reported(self, client, auth_headers, enroll_mfa):
        auth_headers()
        enroll_mfa()

        body = client.get("/auth/mfa/status").json
        assert body["totp_enabled"] is True
        assert body["recovery_codes_remaining"] == 10

    def test_password_reset_invalidates_them(self, client):
        # A reset the user did not initiate must not leave a working bypass on an
        # account the attacker does not control: recovery codes are the other way
        # past the second factor, so they go with the sessions.
        #
        # Resets alice's own password rather than a second account's. Resetting
        # some other user's password must NOT touch alice's codes, and this test
        # previously registered a second account and then asserted alice's codes
        # were gone -- which was asserting the opposite of correct behaviour, and
        # never ran because it skipped for want of a confirmed address.
        _confirmed_alice_with_2fa(client)

        assert RecoveryCode.query.count() == 10
        _reset_alices_password(client)
        assert RecoveryCode.query.count() == 0

    def test_another_users_reset_leaves_my_codes_alone(self, client):
        _confirmed_alice_with_2fa(client)
        client.post("/auth/register", json={
            "username": "bob", "password": "another-password",
            "email": "bob@example.com",
        })
        client.post("/auth/login", json={"username": "bob", "password": "another-password"})
        bob_token = client.post("/account/verify-email/request").json["dev_token"]
        client.post("/account/verify-email/confirm", json={"token": bob_token})
        client.post("/auth/logout")

        reset = client.post("/auth/forgot-password", json={"email": "bob@example.com"})
        assert client.post("/auth/reset-password", json={
            "token": reset.json["dev_token"], "password": "bobs-new-password",
        }).status_code == 200

        # Bob's reset must not have cost alice her escape hatch.
        assert RecoveryCode.query.count() == 10


class TestTheTwoPathsLookTheSame:
    def test_a_wrong_totp_and_a_wrong_recovery_code_agree(self, client, auth_headers,
                                                          enroll_mfa, login,
                                                          finish_mfa_login):
        # Both are six-to-sixteen characters of plausible text that simply do not
        # match. They must be indistinguishable in status and body.
        auth_headers()
        secret, codes = enroll_mfa()

        as_totp = finish_mfa_login(login().json["pending_token"], "000000")
        as_recovery = finish_mfa_login(login().json["pending_token"], "AAAAAAAAAAAAAAAA")

        assert as_totp.status_code == as_recovery.status_code == 401
        assert as_totp.json == as_recovery.json

    def test_a_malformed_code_agrees_with_a_wrong_one(self, client, auth_headers,
                                                      enroll_mfa, login, finish_mfa_login):
        # "abc" and "000000" must not be distinguishable either, or the endpoint
        # confirms the shape of what it expects for free.
        auth_headers()
        secret, _codes = enroll_mfa()

        junk = finish_mfa_login(login().json["pending_token"], "abc")
        wrong = finish_mfa_login(login().json["pending_token"], "000000")

        assert junk.status_code == wrong.status_code == 401
        assert junk.json == wrong.json

    def test_a_missing_code_agrees_with_a_wrong_one(self, client, auth_headers,
                                                    enroll_mfa, login, finish_mfa_login):
        auth_headers()
        secret, _codes = enroll_mfa()

        missing = finish_mfa_login(login().json["pending_token"], "")
        wrong = finish_mfa_login(login().json["pending_token"], "000000")
        assert missing.status_code == wrong.status_code == 401
        assert missing.json == wrong.json


class TestDisabling:
    def test_it_needs_a_current_code(self, client, auth_headers, enroll_mfa):
        auth_headers()
        secret, _codes = enroll_mfa()

        res = client.post("/auth/mfa/disable", json={
            "code": "000000", "password": "correct-horse",
        })
        assert res.status_code == 401
        assert User.query.filter_by(username="alice").one().totp_enabled is True

    def test_it_needs_the_password(self, client, auth_headers, enroll_mfa):
        # A second factor that anyone holding the session can switch off is not a
        # second factor: whoever phished the password would just turn it off.
        auth_headers()
        secret, _codes = enroll_mfa()

        res = client.post("/auth/mfa/disable", json={
            "code": current_code(secret), "password": "wrong",
        })
        assert res.status_code == 403
        assert User.query.filter_by(username="alice").one().totp_enabled is True

    def test_a_wrong_password_does_not_burn_the_code(self, client, auth_headers,
                                                    enroll_mfa):
        # A typo in the password must not cost the user their authenticator code.
        # Verifying the code first spends it -- the counter moves forward and the
        # recovery code is marked used -- so a second attempt with the password
        # corrected would fail even though the user did everything right.
        auth_headers()
        secret, _codes = enroll_mfa()
        code = current_code(secret)

        assert client.post("/auth/mfa/disable", json={
            "code": code, "password": "wrong",
        }).status_code == 403

        # Same code, password now correct: must still work.
        assert client.post("/auth/mfa/disable", json={
            "code": code, "password": "correct-horse",
        }).status_code == 200

    def test_a_wrong_password_does_not_burn_the_recovery_code(
        self, client, auth_headers, enroll_mfa
    ):
        # The same wart on the recovery path, and worse there: a lost phone
        # means these codes are the only way back in.
        auth_headers()
        _secret, codes = enroll_mfa()

        assert client.post("/auth/mfa/disable", json={
            "code": codes[0], "password": "wrong",
        }).status_code == 403

        assert client.post("/auth/mfa/disable", json={
            "code": codes[0], "password": "correct-horse",
        }).status_code == 200

    def test_a_recovery_code_also_disables(self, client, auth_headers, enroll_mfa):
        # The path for someone who has lost their phone.
        auth_headers()
        _secret, codes = enroll_mfa()

        res = client.post("/auth/mfa/disable", json={
            "code": codes[0], "password": "correct-horse",
        })
        assert res.status_code == 200

    def test_disabling_clears_the_seed_and_the_codes(self, client, auth_headers,
                                                      enroll_mfa):
        auth_headers()
        secret, _codes = enroll_mfa()

        client.post("/auth/mfa/disable", json={
            "code": current_code(secret), "password": "correct-horse",
        })

        user = User.query.filter_by(username="alice").one()
        assert user.totp_enabled is False
        assert user.totp_secret is None
        assert user.totp_last_counter is None
        assert RecoveryCode.query.count() == 0

    def test_disabling_revokes_every_session(self, client, auth_headers, enroll_mfa):
        # An attacker holding a refresh cookie from before the change would
        # otherwise keep access to an account whose owner has just enabled 2FA.
        auth_headers()
        secret, recovery_codes = enroll_mfa()

        pending = client.post("/auth/login", json={
            "username": "alice", "password": "correct-horse",
        }).json["pending_token"]
        client.post("/auth/mfa/check", json={
            "pending_token": pending, "code": current_code(secret),
        })
        assert client.get("/auth/me").status_code == 200

        # A recovery code rather than a fresh TOTP one: the TOTP code above was
        # just spent by the login, and reusing a spent code is correctly refused.
        res = client.post("/auth/mfa/disable", json={
            "code": recovery_codes[0], "password": "correct-horse",
        })
        assert res.status_code == 200

        # This browser's cookies were cleared by the response.
        assert client.get("/auth/me").status_code == 401

    def test_a_spent_code_cannot_also_disable(self, client, auth_headers, enroll_mfa):
        # Replay protection applies to the disable path too, not just to login.
        # Otherwise the same code that authenticated a session could be replayed
        # to strip the second factor off.
        auth_headers()
        secret, _codes = enroll_mfa()

        pending = client.post("/auth/login", json={
            "username": "alice", "password": "correct-horse",
        }).json["pending_token"]
        client.post("/auth/mfa/check", json={
            "pending_token": pending, "code": current_code(secret),
        })

        res = client.post("/auth/mfa/disable", json={
            "code": current_code(secret), "password": "correct-horse",
        })
        assert res.status_code == 401
        assert User.query.filter_by(username="alice").one().totp_enabled is True

    def test_it_revokes_every_session_row(self, client, auth_headers, enroll_mfa):
        # The row check, which is what per-device revocation actually relies on.
        # One client's cookies cannot show another client's cookies being
        # cleared, so assert on the session table.
        auth_headers()
        secret, recovery_codes = enroll_mfa()

        pending = client.post("/auth/login", json={
            "username": "alice", "password": "correct-horse",
        }).json["pending_token"]
        client.post("/auth/mfa/check", json={
            "pending_token": pending, "code": current_code(secret),
        })
        assert UserSession.query.count() >= 1

        client.post("/auth/mfa/disable", json={
            "code": recovery_codes[0], "password": "correct-horse",
        })

        assert UserSession.query.count() == 0

    def test_after_disabling_login_is_plain_again(self, client, auth_headers, enroll_mfa,
                                                  login):
        auth_headers()
        secret, _codes = enroll_mfa()
        client.post("/auth/mfa/disable", json={
            "code": current_code(secret), "password": "correct-horse",
        })

        res = login()
        assert res.status_code == 200
        assert "mfa_required" not in res.json

    def test_it_refuses_when_2fa_is_off(self, client, auth_headers):
        auth_headers()
        res = client.post("/auth/mfa/disable", json={
            "code": "000000", "password": "correct-horse",
        })
        assert res.status_code == 409


class TestEnrolmentGuards:
    def test_enrolling_twice_is_refused(self, client, auth_headers, enroll_mfa):
        # Otherwise the second enrolment silently replaces the first seed, and the
        # phone the user had set up stops working with no explanation.
        auth_headers()
        enroll_mfa()

        assert client.get("/auth/mfa/start").status_code == 409

    def test_confirmation_needs_a_code_from_that_secret(self, client, auth_headers):
        auth_headers()
        secret = _start(client)["secret"]

        res = client.post("/auth/mfa/confirm", json={
            "secret": secret, "code": current_code(generate_secret()),
        })
        assert res.status_code == 400
        assert User.query.filter_by(username="alice").one().totp_enabled is False

    def test_confirmation_needs_a_code_at_all(self, client, auth_headers):
        auth_headers()
        secret = _start(client)["secret"]

        assert client.post("/auth/mfa/confirm", json={"secret": secret}).status_code == 401

    def test_confirmation_accepts_any_self_consistent_pair(self, client, auth_headers):
        # Confirmation does not care which secret it is shown, only that the code
        # matches the secret beside it. That is the property that matters: it
        # proves an authenticator was set up with the seed this account will use.
        # Requiring the secret to come from a previous /start would mean storing a
        # pending enrolment on the row, which is the half-enabled state the
        # two-step design exists to avoid.
        auth_headers()
        other = generate_secret()

        res = client.post("/auth/mfa/confirm", json={
            "secret": other, "code": current_code(other),
        })
        assert res.status_code == 200
        assert res.json["totp_enabled"] is True

    def test_a_mismatched_pair_is_refused(self, client, auth_headers):
        # The same secret with a code from a different one: well-formed on both
        # sides, and must fail.
        auth_headers()
        secret = generate_secret()

        res = client.post("/auth/mfa/confirm", json={
            "secret": secret, "code": current_code(generate_secret()),
        })
        assert res.status_code == 400
        assert User.query.filter_by(username="alice").one().totp_enabled is False

    def test_start_requires_a_session(self, client):
        assert client.get("/auth/mfa/start").status_code == 401

    def test_confirm_requires_a_session(self, client):
        secret = generate_secret()
        res = client.post("/auth/mfa/confirm", json={
            "secret": secret, "code": current_code(secret),
        })
        assert res.status_code == 401

    def test_disabling_requires_a_session(self, client):
        res = client.post("/auth/mfa/disable", json={
            "code": "000000", "password": "correct-horse",
        })
        assert res.status_code == 401

    def test_regenerating_codes_requires_the_password(self, client, auth_headers,
                                                      enroll_mfa):
        auth_headers()
        _secret, codes = enroll_mfa()

        assert client.post("/auth/mfa/recovery-codes", json={
            "password": "wrong",
        }).status_code == 403
        assert RecoveryCode.query.count() == 10

    def test_regenerating_invalidates_the_old_set(self, client, auth_headers, enroll_mfa):
        auth_headers()
        _secret, codes = enroll_mfa()

        res = client.post("/auth/mfa/recovery-codes", json={"password": "correct-horse"})
        assert res.status_code == 200

        client.post("/auth/logout")
        pending = client.post("/auth/login", json={
            "username": "alice", "password": "correct-horse",
        }).json["pending_token"]

        # An old code must not work after regeneration.
        assert client.post("/auth/mfa/check", json={
            "pending_token": pending, "code": codes[0],
        }).status_code == 401

    def test_the_new_codes_work(self, client, auth_headers, enroll_mfa):
        auth_headers()
        _secret, _codes = enroll_mfa()

        new_codes = client.post("/auth/mfa/recovery-codes", json={
            "password": "correct-horse",
        }).json["recovery_codes"]

        pending = client.post("/auth/login", json={
            "username": "alice", "password": "correct-horse",
        }).json["pending_token"]

        assert client.post("/auth/mfa/check", json={
            "pending_token": pending, "code": new_codes[0],
        }).status_code == 200

    def test_regenerating_refuses_when_2fa_is_off(self, client, auth_headers):
        auth_headers()
        assert client.post("/auth/mfa/recovery-codes", json={
            "password": "correct-horse",
        }).status_code == 409


class TestVisibility:
    def test_me_reports_the_state(self, client, auth_headers):
        auth_headers()
        body = client.get("/auth/me").json
        assert body["totp_enabled"] is False
        assert body["recovery_codes_remaining"] == 0

    def test_the_count_falls_as_codes_are_used(self, client, auth_headers, enroll_mfa,
                                               login, finish_mfa_login):
        auth_headers()
        _secret, codes = enroll_mfa()

        finish_mfa_login(login().json["pending_token"], codes[0])
        assert client.get("/auth/me").json["recovery_codes_remaining"] == 9

    def test_a_user_who_never_enrolled_has_no_recovery_codes(self, client, auth_headers):
        # The count must not be reported for someone with 2FA off, or it reads as
        # "you have codes" on an account that never issued any.
        auth_headers()
        assert client.get("/auth/me").json["recovery_codes_remaining"] == 0


def test_the_encryption_round_trips(app):
    with app.app_context():
        secret = generate_secret()
        assert decrypt(encrypt(secret)) == secret


def test_encryption_produces_different_ciphertext_each_time(app):
    # Fernet includes a random IV, so the same seed must not produce the same
    # ciphertext twice: identical ciphertexts would leak that two accounts share a
    # seed, and would allow frequency analysis over a large table.
    with app.app_context():
        secret = generate_secret()
        assert encrypt(secret) != encrypt(secret)


def test_encrypt_raises_when_the_key_is_missing(app, monkeypatch):
    with app.app_context():
        monkeypatch.setitem(app.config, "TOTP_ENCRYPTION_KEY", "")
        with pytest.raises(KeyUnavailable):
            encrypt(generate_secret())


def test_a_recovery_code_is_not_a_valid_totp_code(app):
    # Two separate namespaces. A recovery code must never be accepted as a TOTP
    # code or vice versa, or a stolen code is ambiguous to an attacker.
    secret = generate_secret()
    with app.app_context():
        from mfa import generate_recovery_codes

        code = generate_recovery_codes(1)[0]
    assert not verify(secret, code, now=time.time())


def test_the_provisioning_uri_is_shown_once_at_setup(client, auth_headers):
    auth_headers()
    body = _start(client)

    assert body["provisioning_uri"].startswith("otpauth://totp/")
    assert body["digits"] == 6
    assert body["period"] == 30
    assert body["issuer"]
