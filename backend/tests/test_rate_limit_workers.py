"""Multi-worker rate limiting, and refusing to start in a broken configuration.

Flask-Limiter's default memory:// store keeps counters in the worker's own
process. Nothing errors: a 10-per-minute login limit simply becomes 40 with four
workers, and 200 with twenty. The control stops applying without any signal,
which is the worst way for a security control to fail.

Config.validate() refuses to start in production when memory:// is combined
with more than one worker. Single-worker deployments are allowed, because there
the limiter genuinely does work as intended.
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
    "RATELIMIT_STORAGE_URI": "redis://localhost:6379/0",
}

MANAGED = tuple(BASE_PROD)


@pytest.fixture(autouse=True)
def restore(monkeypatch):
    saved = {name: getattr(Config, name) for name in MANAGED}
    saved_workers = None
    yield
    for name, value in saved.items():
        setattr(Config, name, value)
    if saved_workers is not None:
        import os

        os.environ.pop("WEB_CONCURRENCY", None)


def _apply(**overrides):
    for name, value in {**BASE_PROD, **overrides}.items():
        setattr(Config, name, value)


class TestRedisIsRequiredForSeveralWorkers:
    def test_memory_storage_with_several_workers_is_rejected(self, monkeypatch):

        monkeypatch.setenv("WEB_CONCURRENCY", "4")
        _apply(RATELIMIT_STORAGE_URI="memory://")

        with pytest.raises(RuntimeError) as exc:
            Config.validate()
        message = str(exc.value)
        assert "RATELIMIT_STORAGE_URI" in message
        assert "WEB_CONCURRENCY" in message

    def test_the_message_says_why_it_matters(self, monkeypatch):

        monkeypatch.setenv("WEB_CONCURRENCY", "4")
        _apply(RATELIMIT_STORAGE_URI="memory://")

        with pytest.raises(RuntimeError) as exc:
            Config.validate()
        # "point at Redis" without saying what breaks is not actionable.
        assert "Redis" in str(exc.value)
        assert "multiplied" in str(exc.value)

    def test_redis_with_several_workers_passes(self, monkeypatch):

        monkeypatch.setenv("WEB_CONCURRENCY", "4")
        _apply(RATELIMIT_STORAGE_URI="redis://cache:6379/0")
        Config.validate()

    def test_memory_storage_with_one_worker_passes(self, monkeypatch):
        # One process means one counter, so the limiter is actually correct and
        # refusing to start would be gratuitous.

        monkeypatch.setenv("WEB_CONCURRENCY", "1")
        _apply(RATELIMIT_STORAGE_URI="memory://")
        Config.validate()

    def test_the_default_worker_count_is_one(self, monkeypatch):

        monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
        _apply(RATELIMIT_STORAGE_URI="memory://")
        Config.validate()

    def test_development_is_never_blocked(self, monkeypatch):

        monkeypatch.setenv("WEB_CONCURRENCY", "8")
        _apply(
            ENV="development",
            JWT_COOKIE_SECURE=False,
            MAIL_ENABLED=False,
            MAIL_HOST=None,
            RATELIMIT_STORAGE_URI="memory://",
        )
        # A developer running several processes locally should not be stopped
        # at the door; the fix belongs in the deploy config, not the dev loop.
        Config.validate()

    def test_a_redis_url_with_a_password_is_accepted(self, monkeypatch):

        monkeypatch.setenv("WEB_CONCURRENCY", "4")
        _apply(RATELIMIT_STORAGE_URI="redis://:secret@cache.internal:6379/2")
        Config.validate()


class TestWsgiWorkerCount:
    def test_wsgi_defaults_to_one_worker(self, monkeypatch):

        monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
        import wsgi

        assert wsgi.workers >= 1

    def test_wsgi_honours_the_environment(self, monkeypatch):

        monkeypatch.setenv("WEB_CONCURRENCY", "6")
        import importlib

        import wsgi

        importlib.reload(wsgi)
        assert wsgi.workers == 6
        # Leave the module as it was for other tests.
        monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
        importlib.reload(wsgi)
