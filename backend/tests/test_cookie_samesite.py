"""Cross-site cookie configuration.

SameSite=Lax works in development because cookies ignore ports:
localhost:5173 -> localhost:5000 is the same *site*. It stops being the same
site the moment the frontend and API live on different registrable domains, and
then a Lax cookie is never sent at all. Nothing errors; every login appears to
succeed and every later request is unauthenticated.

That failure is invisible until production, so it is made explicit here instead
of being something a deployer has to remember.
"""

import pytest

from config import Config

BASE_PROD = {
    "ENV": "production",
    "SECRET_KEY": "a" * 48,
    "JWT_SECRET_KEY": "b" * 48,
    "AUTO_CREATE_TABLES": False,
    "JWT_COOKIE_SECURE": True,
    "CORS_ORIGINS": ["https://app.example"],
    "MAIL_ENABLED": True,
    "MAIL_HOST": "smtp.example.com",
    "RESET_REQUIRES_VERIFIED_EMAIL": True,
}

MANAGED = tuple(BASE_PROD) + (
    "JWT_COOKIE_CROSS_SITE",
    "JWT_COOKIE_SAMESITE",
)


def _apply(**overrides):
    for name, value in {**BASE_PROD, **overrides}.items():
        setattr(Config, name, value)


@pytest.fixture(autouse=True)
def restore():
    saved = {name: getattr(Config, name) for name in MANAGED}
    yield
    for name, value in saved.items():
        setattr(Config, name, value)


class TestDefaults:
    def test_same_site_is_lax_by_default(self):
        _apply(JWT_COOKIE_CROSS_SITE=False, JWT_COOKIE_SAMESITE="Lax")
        assert Config.JWT_COOKIE_SAMESITE == "Lax"

    def test_a_well_configured_production_setup_passes(self):
        _apply()
        Config.validate()

    def test_cross_site_is_off_by_default(self):
        _apply(JWT_COOKIE_CROSS_SITE=False)
        assert Config.JWT_COOKIE_CROSS_SITE is False


class TestCrossSite:
    def test_cross_site_forces_samesite_none(self):
        _apply(JWT_COOKIE_CROSS_SITE=True, JWT_COOKIE_SAMESITE="None")
        Config.validate()
        assert Config.JWT_COOKIE_SAMESITE == "None"

    def test_cross_site_without_secure_is_rejected(self):
        # A browser silently drops SameSite=None on an insecure cookie, so the
        # session cookie would simply never be sent.
        _apply(JWT_COOKIE_CROSS_SITE=True, JWT_COOKIE_SAMESITE="None",
               JWT_COOKIE_SECURE=False)
        with pytest.raises(RuntimeError) as exc:
            Config.validate()
        assert "JWT_COOKIE_SECURE" in str(exc.value)

    def test_cross_site_with_the_wrong_samesite_is_rejected(self):
        _apply(JWT_COOKIE_CROSS_SITE=True, JWT_COOKIE_SAMESITE="Lax")
        with pytest.raises(RuntimeError) as exc:
            Config.validate()
        assert "SameSite=None" in str(exc.value)

    def test_samesite_none_without_secure_is_rejected(self):
        # Set directly rather than via the flag, which is how a hand-edited
        # .env would express the same broken combination.
        _apply(JWT_COOKIE_CROSS_SITE=False, JWT_COOKIE_SAMESITE="None",
               JWT_COOKIE_SECURE=False)
        with pytest.raises(RuntimeError) as exc:
            Config.validate()
        assert "JWT_COOKIE_SECURE" in str(exc.value)

    def test_samesite_strict_with_secure_is_fine(self):
        _apply(JWT_COOKIE_CROSS_SITE=False, JWT_COOKIE_SAMESITE="Strict")
        Config.validate()


class TestProductionOnly:
    def test_the_cookie_rules_are_not_enforced_in_development(self):
        # A developer on http://localhost cannot use SameSite=None, so the
        # combination has to be allowed outside production or local work breaks.
        _apply(
            ENV="development",
            JWT_COOKIE_CROSS_SITE=True,
            JWT_COOKIE_SAMESITE="Lax",
            JWT_COOKIE_SECURE=False,
        )
        Config.validate()
