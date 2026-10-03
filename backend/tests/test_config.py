import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config  # noqa: E402


@pytest.fixture(autouse=True)
def restore_config():
    """These tests mutate class attributes; put them back afterwards."""
    saved = {name: getattr(Config, name) for name in
             ("ENV", "SECRET_KEY", "JWT_SECRET_KEY", "AUTO_CREATE_TABLES",
              "JWT_COOKIE_SECURE", "CORS_ORIGINS")}
    yield
    for name, value in saved.items():
        setattr(Config, name, value)


def _set(**overrides):
    for name, value in overrides.items():
        setattr(Config, name, value)


class _GoodProd:
    ENV = "production"
    SECRET_KEY = "a" * 48
    JWT_SECRET_KEY = "b" * 48
    AUTO_CREATE_TABLES = False
    JWT_COOKIE_SECURE = True
    CORS_ORIGINS = ["https://app.example"]


def _apply(cls):
    for name in ("ENV", "SECRET_KEY", "JWT_SECRET_KEY", "AUTO_CREATE_TABLES",
                 "JWT_COOKIE_SECURE", "CORS_ORIGINS"):
        setattr(Config, name, getattr(cls, name))


# --- Happy paths ----------------------------------------------------------
def test_dev_config_passes_validation():
    _set(ENV="development", AUTO_CREATE_TABLES=False)
    Config.validate()


def test_well_configured_production_passes():
    _apply(_GoodProd)
    Config.validate()


# --- Production guards ----------------------------------------------------
def test_production_with_placeholder_secrets_is_rejected():
    _set(ENV="production",
         SECRET_KEY=Config.__dict__.get("SECRET_KEY", "dev-only-insecure-secret-change-me-32ch"),
         AUTO_CREATE_TABLES=False, JWT_COOKIE_SECURE=True,
         CORS_ORIGINS=["https://app.example"])
    Config.SECRET_KEY = "dev-only-insecure-secret-change-me-32ch"
    Config.JWT_SECRET_KEY = "dev-only-insecure-jwt-secret-change-me-32"
    with pytest.raises(RuntimeError) as exc:
        Config.validate()
    assert "SECRET_KEY" in str(exc.value)


def test_production_with_short_secret_is_rejected():
    _apply(_GoodProd)
    Config.SECRET_KEY = "too-short"
    with pytest.raises(RuntimeError) as exc:
        Config.validate()
    assert "SECRET_KEY" in str(exc.value)


def test_production_with_create_all_on_is_rejected():
    _apply(_GoodProd)
    Config.AUTO_CREATE_TABLES = True
    with pytest.raises(RuntimeError) as exc:
        Config.validate()
    assert "AUTO_CREATE_TABLES" in str(exc.value)
    assert "flask db upgrade" in str(exc.value)


def test_production_without_secure_cookie_is_rejected():
    _apply(_GoodProd)
    Config.JWT_COOKIE_SECURE = False
    with pytest.raises(RuntimeError) as exc:
        Config.validate()
    assert "JWT_COOKIE_SECURE" in str(exc.value)


def test_production_with_wildcard_cors_is_rejected():
    _apply(_GoodProd)
    Config.CORS_ORIGINS = ["*"]
    with pytest.raises(RuntimeError) as exc:
        Config.validate()
    assert "CORS_ORIGINS" in str(exc.value)


def test_all_production_problems_are_reported_at_once():
    _apply(_GoodProd)
    Config.AUTO_CREATE_TABLES = True
    Config.JWT_COOKIE_SECURE = False
    Config.CORS_ORIGINS = ["*"]
    with pytest.raises(RuntimeError) as exc:
        Config.validate()
    message = str(exc.value)
    assert "AUTO_CREATE_TABLES" in message
    assert "JWT_COOKIE_SECURE" in message
    assert "CORS_ORIGINS" in message


# --- Cookie / session defaults --------------------------------------------
def test_tokens_are_read_from_cookies_not_headers():
    assert Config.JWT_TOKEN_LOCATION == ["cookies"]


def test_create_all_is_off_by_default():
    """Migrations own the schema, so create_all must not run implicitly."""
    assert Config.AUTO_CREATE_TABLES is False


def test_session_lifetimes_are_sane():
    assert Config.JWT_ACCESS_TOKEN_EXPIRES.total_seconds() > 0
    assert Config.JWT_REFRESH_TOKEN_EXPIRES > Config.JWT_ACCESS_TOKEN_EXPIRES


def test_cookie_is_secure_in_production_only():
    assert (Config.ENV == "production") == Config.JWT_COOKIE_SECURE


def test_cors_supports_credentials():
    assert Config.CORS_SUPPORTS_CREDENTIALS is True


def test_default_cors_is_not_a_wildcard():
    assert "*" not in Config.CORS_ORIGINS
    assert Config.CORS_ORIGINS


# --- Rate limit defaults --------------------------------------------------
def test_rate_limits_are_configured():
    assert Config.RATELIMIT_ENABLED is True
    assert Config.LOGIN_RATE_LIMIT
    assert Config.REGISTER_RATE_LIMIT
    assert Config.CALCULATE_RATE_LIMIT
    assert Config.READ_RATE_LIMIT
    assert Config.RATELIMIT_STORAGE_URI


# --- Input limits ---------------------------------------------------------
def test_input_limits_are_sane():
    assert Config.MIN_PASSWORD_LENGTH >= 8
    assert Config.MAX_PASSWORD_LENGTH <= 128
    assert Config.MAX_CAR_KM > 0
    assert Config.MAX_ELECTRICITY_KWH > 0
    assert Config.MAX_MEALS > 0
    assert Config.MAX_CONTENT_LENGTH > 0
    assert Config.MIN_USERNAME_LENGTH >= 3


# --- Env parsing ----------------------------------------------------------
def test_int_env_ignores_junk(monkeypatch):
    from config import _int_env

    monkeypatch.setenv("SOME_INT", "not-a-number")
    assert _int_env("SOME_INT", 7) == 7

    monkeypatch.setenv("SOME_INT", "3")
    assert _int_env("SOME_INT", 7) == 3

    monkeypatch.setenv("SOME_INT", "0")
    assert _int_env("SOME_INT", 7, minimum=1) == 1


def test_bool_env(monkeypatch):
    from config import _bool_env

    monkeypatch.delenv("SOME_BOOL", raising=False)
    assert _bool_env("SOME_BOOL", default=True) is True

    for truthy in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv("SOME_BOOL", truthy)
        assert _bool_env("SOME_BOOL") is True

    for falsy in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("SOME_BOOL", falsy)
        assert _bool_env("SOME_BOOL") is False
