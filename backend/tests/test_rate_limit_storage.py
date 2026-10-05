"""The rate limiter must actually use the storage it was configured with.

This file exists because of a bug that made every other test in the project
misleading. extensions.py passed `storage_uri="memory://"` to the Limiter
constructor, and Flask-Limiter resolves storage as
`constructor_arg or app_config`. The constructor argument therefore won, so:

- RATELIMIT_STORAGE_URI was accepted, stored in config and read by
  Config.validate(), which is what refuses to start a multi-worker production
  deployment without Redis;
- and the limiter counted in per-process memory regardless.

So an operator could follow the documentation exactly, set the Redis URL, watch
the app refuse to start without it, set it, see the app boot happily -- and the
rate limits would still be multiplied by the worker count. The security control
was not applying, behind the configuration that was supposed to turn it on.

The lesson these tests encode: assert on the object's real state, never on the
configuration value that is supposed to drive it.
"""

import os
import sys

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

from app import create_app  # noqa: E402
from config import Config  # noqa: E402
from extensions import limiter  # noqa: E402


class _WithStorage(Config):
    ENV = "development"
    TESTING = True
    AUTO_CREATE_TABLES = False
    CHECK_SCHEMA_ON_STARTUP = False
    RATELIMIT_ENABLED = True


def _storage_class(uri):
    """The storage class Flask-Limiter ends up with for `uri`."""
    class _Configured(_WithStorage):
        RATELIMIT_STORAGE_URI = uri

    create_app(_Configured)
    return type(limiter._storage).__name__


class TestTheConfiguredStorageIsTheStorageUsed:
    def test_a_redis_url_produces_redis_storage(self):
        # Not asserted against config: that is the check that was already passing
        # while the app ignored the setting.
        #
        # 127.0.0.1 rather than localhost, and the storage class is read without
        # any connection being made -- but naming another machine's Redis by
        # hostname would make the test depend on whatever else the developer
        # happens to be running.
        assert _storage_class("redis://127.0.0.1:6379/0") == "RedisStorage"

    def test_memory_stays_memory(self):
        assert _storage_class("memory://") == "MemoryStorage"

    def test_the_default_is_in_memory(self):
        from config import Config as RealConfig

        assert RealConfig.RATELIMIT_STORAGE_URI == "memory://"
        assert _storage_class(RealConfig.RATELIMIT_STORAGE_URI) == "MemoryStorage"


class TestTheConstructorCannotOverrideTheConfig:
    def test_no_storage_uri_is_passed_to_the_limiter(self):
        # The regression itself, stated directly. Passing storage_uri to the
        # constructor silently beats the config, so it must not be passed at all.
        import inspect

        source = inspect.getsource(__import__("extensions"))
        limiter_block = source.split("limiter = Limiter(", 1)[1].split(")", 1)[0]
        assert "storage_uri" not in limiter_block, (
            "a constructor storage_uri overrides RATELIMIT_STORAGE_URI"
        )

    def test_the_constructor_argument_defaults_to_none(self):
        assert limiter._storage_uri is None


class TestValidateChecksTheSettingThatMatters:
    """Config.validate() is only useful if it reflects reality.

    It reads the config value, which is right -- the config is the input. But the
    reason it is worth reading is that the config now reaches the limiter, which
    the previous test proves. These two together are the guarantee; either alone
    is not.
    """

    def test_production_with_redis_and_two_workers_is_accepted(self, monkeypatch):
        monkeypatch.setenv("WEB_CONCURRENCY", "2")
        _apply_production(RATELIMIT_STORAGE_URI="redis://cache:6379/0")
        Config.validate()

    def test_production_with_memory_and_two_workers_is_refused(self, monkeypatch):
        monkeypatch.setenv("WEB_CONCURRENCY", "2")
        _apply_production(RATELIMIT_STORAGE_URI="memory://")
        with pytest.raises(RuntimeError) as exc:
            Config.validate()
        assert "RATELIMIT_STORAGE_URI" in str(exc.value)


def _apply_production(**overrides):
    """Point Config at a valid production setup, so only the overrides can fail."""
    for name, value in {
        "ENV": "production",
        "SECRET_KEY": "a" * 48,
        "JWT_SECRET_KEY": "b" * 48,
        "AUTO_CREATE_TABLES": False,
        "JWT_COOKIE_SECURE": True,
        "CORS_ORIGINS": ["https://app.example"],
        "MAIL_ENABLED": True,
        "MAIL_HOST": "smtp.example.com",
        "RESET_REQUIRES_VERIFIED_EMAIL": True,
        "TOTP_ENCRYPTION_KEY": b"YVGGsJ3cy-WpnsE3YfNtl84-mzfpW9kTcuD0y6mqNjA=",
        **overrides,
    }.items():
        setattr(Config, name, value)
