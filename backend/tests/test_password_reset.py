"""Password reset: token handling, enumeration resistance, and expiry."""

from datetime import UTC, datetime, timedelta

import pytest

from models import User
from passwords import (
    TOKEN_TTL,
    generate_token,
    hash_password,
    hash_token,
    is_expired,
    verify_password,
    verify_token,
)


class TestTokens:
    def test_generate_returns_raw_and_hash(self):
        raw, token_hash = generate_token()
        assert raw and token_hash
        assert raw != token_hash, "the raw token must never be stored"
        assert hash_token(raw) == token_hash

    def test_tokens_are_unique(self):
        assert len({generate_token()[0] for _ in range(50)}) == 50

    def test_tokens_are_url_safe_and_long_enough(self):
        raw, _ = generate_token()
        assert len(raw) >= 32
        assert all(c.isalnum() or c in "-_" for c in raw)

    def test_verify_accepts_the_right_token(self):
        raw, token_hash = generate_token()
        assert verify_token(raw, token_hash)

    def test_verify_rejects_a_different_token(self):
        _, token_hash = generate_token()
        other, _ = generate_token()
        assert not verify_token(other, token_hash)

    @pytest.mark.parametrize("raw, stored", [("", "abc"), ("abc", ""), (None, "abc"), ("abc", None)])
    def test_verify_rejects_junk_without_raising(self, raw, stored):
        assert not verify_token(raw, stored)


class TestExpiry:
    def test_fresh_token_is_not_expired(self):
        assert not is_expired(datetime.now(UTC))

    def test_old_token_is_expired(self):
        assert is_expired(datetime.now(UTC) - TOKEN_TTL - timedelta(minutes=1))

    def test_none_is_expired(self):
        assert is_expired(None)

    def test_naive_timestamp_is_treated_as_utc(self):
        # SQLite drops tzinfo, so this is the shape a loaded value takes.
        naive = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1)
        assert not is_expired(naive)
        assert is_expired(naive - TOKEN_TTL)


class TestPasswordHelpers:
    def test_hash_and_verify_round_trip(self):
        assert verify_password(hash_password("correct-horse"), "correct-horse")

    def test_wrong_password_fails(self):
        assert not verify_password(hash_password("correct-horse"), "wrong")

    @pytest.mark.parametrize("stored, candidate", [("", "x"), ("x", ""), (None, "x")])
    def test_junk_does_not_raise(self, stored, candidate):
        assert not verify_password(stored, candidate)


class TestUserTokenBinding:
    def _user_with_token(self, **kwargs):
        user = User(username="alice", email="a@example.com")
        user.set_password("correct-horse")
        raw, token_hash = generate_token()
        user.request_password_reset(token_hash, **kwargs)
        return user, raw

    def test_matches_the_issued_token(self):
        user, raw = self._user_with_token()
        assert user.matches_reset_token(raw)

    def test_rejects_a_different_token(self):
        user, _ = self._user_with_token()
        other, _ = generate_token()
        assert not user.matches_reset_token(other)

    def test_rejects_after_expiry(self):
        stale = datetime.now(UTC) - TOKEN_TTL - timedelta(minutes=1)
        user, raw = self._user_with_token(now=stale)
        assert not user.matches_reset_token(raw)

    def test_no_token_means_no_match(self):
        user = User(username="alice")
        assert not user.matches_reset_token("anything")

    def test_applying_a_password_burns_the_token(self):
        user, raw = self._user_with_token()
        user.apply_new_password(hash_password("brand-new-password"))
        assert not user.matches_reset_token(raw), "a reset token must be single use"
        assert user.password_reset_token_hash is None
        assert user.check_password("brand-new-password")


class TestEmailMasking:
    def test_masks_the_local_part(self):
        assert User(username="a").to_dict().get("email") is None
        u = User(username="dave")
        u.email = "dave@example.com"
        assert u.to_dict()["email"] == "d***e@example.com"
        assert u.to_dict()["has_email"] is True

    def test_absent_email_is_flagged_not_hidden(self):
        u = User(username="dave")
        payload = u.to_dict()
        assert payload["has_email"] is False
        assert "email" not in payload

    def test_never_leaks_the_token_hash(self):
        u = User(username="dave")
        raw, token_hash = generate_token()
        u.request_password_reset(token_hash)
        serialised = repr(u.to_dict())
        assert token_hash not in serialised
        assert raw not in serialised
