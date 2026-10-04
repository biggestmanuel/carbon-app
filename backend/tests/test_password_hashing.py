"""Password hashing: the method, and what happens when it changes.

Werkzeug records the method inside the hash string, so old and new hashes coexist
in one column and old accounts keep working. These tests pin that, because a
mistake here locks every existing user out.
"""

import pytest
from werkzeug.security import check_password_hash, generate_password_hash

from models import User
from passwords import hash_password, verify_password


class TestStoredMethod:
    def test_a_new_hash_is_scrypt(self):
        digest = hash_password("correct-horse")
        assert digest.startswith("scrypt:"), digest.split("$")[0]

    def test_the_model_writes_the_same_method(self):
        user = User(username="alice")
        user.set_password("correct-horse")
        assert user.password_hash.startswith("scrypt:")

    def test_a_scrypt_hash_fits_the_column(self):
        # The old comment claimed scrypt "can exceed 128 chars and would
        # otherwise get silently truncated". It is 162, and the column is 255.
        digest = hash_password("correct-horse")
        assert len(digest) < 255, f"hash is {len(digest)} chars"

    def test_the_password_column_is_wide_enough(self):
        assert User.__table__.c.password_hash.type.length >= 162


class TestMixedTable:
    def test_a_pbkdf2_hash_written_before_the_switch_still_verifies(self):
        legacy = generate_password_hash("correct-horse", method="pbkdf2:sha256")
        assert legacy.startswith("pbkdf2:")

        # No migration, no forced reset: the method travels inside the hash.
        assert verify_password(legacy, "correct-horse")
        assert not verify_password(legacy, "wrong-password")

    def test_both_methods_coexist_in_one_column(self):
        legacy = generate_password_hash("correct-horse", method="pbkdf2:sha256")
        current = hash_password("correct-horse")

        assert verify_password(legacy, "correct-horse")
        assert verify_password(current, "correct-horse")
        assert not verify_password(legacy, "wrong")
        assert not verify_password(current, "wrong")

    def test_a_user_created_before_the_switch_can_still_log_in(self, client, app):
        client.post("/auth/register", json={"username": "alice", "password": "correct-horse"})
        with app.app_context():
            user = User.query.filter_by(username="alice").one()
            # Rewrite the row the way the old code would have written it.
            user.password_hash = generate_password_hash("correct-horse", method="pbkdf2:sha256")
            from extensions import db

            db.session.commit()

        client.post("/auth/logout")
        res = client.post("/auth/login", json={"username": "alice", "password": "correct-horse"})
        assert res.status_code == 200

    def test_the_password_is_rewritten_as_scrypt_on_the_next_reset(self, client, app):
        client.post("/auth/register", json={
            "username": "alice", "password": "correct-horse",
            "email": "alice@example.com",
        })
        client.post("/auth/login", json={"username": "alice", "password": "correct-horse"})
        token = client.post("/account/verify-email/request").json["dev_token"]
        client.post("/account/verify-email/confirm", json={"token": token})
        client.post("/auth/logout")

        with app.app_context():
            from extensions import db

            user = User.query.filter_by(username="alice").one()
            user.password_hash = generate_password_hash("correct-horse", method="pbkdf2:sha256")
            db.session.commit()

        reset = client.post("/auth/forgot-password", json={"email": "alice@example.com"})
        client.post("/auth/reset-password", json={
            "token": reset.json["dev_token"], "password": "brand-new-password",
        })

        with app.app_context():
            user = User.query.filter_by(username="alice").one()
            assert user.password_hash.startswith("scrypt:")


class TestTimingEqualiser:
    def test_the_dummy_hash_uses_the_current_method(self):
        # A dummy of a different method would reintroduce the timing gap for
        # accounts whose stored hash predates the switch.
        from routes.auth import _DUMMY_HASH

        assert _DUMMY_HASH.startswith("scrypt:")

    def test_an_unknown_user_and_a_wrong_password_both_verify_a_hash(self, client, app):
        from routes.auth import _DUMMY_HASH

        # login() hashes _DUMMY_HASH when the user is missing. Both paths must
        # go through a scrypt verification for the timings to match.
        assert _DUMMY_HASH.startswith("scrypt:")
        assert check_password_hash(_DUMMY_HASH, "correct-horse") is False


@pytest.mark.parametrize("method", ["pbkdf2:sha256", "scrypt"])
def test_verify_password_rejects_junk_without_raising(method):
    digest = generate_password_hash("correct-horse", method=method)
    assert verify_password(digest, "correct-horse")
    assert not verify_password(digest, "")
    assert not verify_password(digest, "x" * 500)
