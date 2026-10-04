"""Breached-password checking via the Have I Been Pwned range API.

Two properties matter more than the feature itself:

1. The password never leaves the machine. Only the first five characters of its
   SHA-1 digest are sent, so the assertion here is about the request URL, not
   just about the response handling.
2. It fails open. A breach check that can lock every user out during someone
   else's outage is worse than no breach check.
"""

import hashlib
import io
import urllib.error

import pytest

from breached import API_ROOT, PREFIX_LENGTH, is_breached, sha1_prefix


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False


def _opener(body="", error=None):
    """Records the URL requested and returns `body` (or raises `error`)."""
    calls = []

    def _open(url):
        calls.append(url)
        if error is not None:
            raise error
        return FakeResponse(body.encode())

    _open.calls = calls
    return _open


def _suffix(password):
    return sha1_prefix(password, length=40)[PREFIX_LENGTH:]


class TestKAnonymity:
    def test_only_the_prefix_is_sent(self):
        password = "correct-horse-battery-staple"
        opener = _opener()
        is_breached(password, fetch=opener)

        prefix = sha1_prefix(password)
        assert opener.calls == [f"{API_ROOT}/{prefix}"]
        # The full digest must not appear anywhere in the URL.
        full = sha1_prefix(password, length=40)
        assert full not in opener.calls[0]
        assert full[:PREFIX_LENGTH] in opener.calls[0]

    def test_the_password_itself_is_never_sent(self):
        password = "correct-horse-battery-staple"
        opener = _opener()
        is_breached(password, fetch=opener)
        assert password not in opener.calls[0]

    def test_the_prefix_is_five_upper_hex_characters(self):
        prefix = sha1_prefix("anything")
        assert len(prefix) == PREFIX_LENGTH
        assert prefix == prefix.upper()
        assert all(c in "0123456789ABCDEF" for c in prefix)

    def test_it_uses_sha1_as_the_api_requires(self):
        # The corpus is indexed by SHA-1; using anything else silently returns
        # "not breached" for every password.
        expected = hashlib.sha1(b"hunter2", usedforsecurity=False).hexdigest().upper()
        assert sha1_prefix("hunter2", length=40) == expected


class TestDetection:
    def test_it_finds_a_known_breached_password(self):
        password = "password"
        body = f"{_suffix(password)}:123456\r\nAAAA:1\r\n"
        assert is_breached(password, fetch=_opener(body)) is True

    def test_it_ignores_other_entries_in_the_same_prefix(self):
        password = "some-unique-password"
        body = f"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA:9\r\n{_suffix(password)}:2\r\n"
        assert is_breached(password, fetch=_opener(body)) is True

    def test_an_unlisted_password_is_not_breached(self):
        body = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA:9\r\nBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB:1\r\n"
        assert is_breached("some-unique-password", fetch=_opener(body)) is False

    def test_an_empty_response_means_not_breached(self):
        assert is_breached("anything", fetch=_opener("")) is False

    def test_matching_is_case_insensitive_on_the_suffix(self):
        # The API returns uppercase; a lowercase digest must still match.
        password = "mixedcase-password"
        body = f"{_suffix(password).lower()}:4\r\n"
        assert is_breached(password, fetch=_opener(body)) is True

    def test_an_empty_password_is_not_breached(self):
        # No request should be made at all.
        opener = _opener()
        assert is_breached("", fetch=opener) is False
        assert opener.calls == []


class TestFailsOpen:
    @pytest.mark.parametrize("error", [
        urllib.error.URLError("connection refused"),
        urllib.error.HTTPError("u", 503, "unavailable", None, None),
        TimeoutError("timed out"),
        OSError("network down"),
    ])
    def test_a_network_failure_allows_the_password(self, error):
        # Deliberate: refusing here would lock every user out when the service
        # has an outage.
        assert is_breached("whatever", fetch=_opener(error=error)) is False

    def test_a_timeout_is_not_an_error(self):
        assert is_breached("whatever", fetch=_opener(error=TimeoutError())) is False

    def test_undecodable_bytes_do_not_raise(self):
        opener = _opener("\xff\xfe not utf-8 \xff")
        assert is_breached("whatever", fetch=opener) is False


class TestOverHttp:
    """The wiring the routes use, with a stubbed opener.

    The check is off by default in the suite so that no test depends on a third
    party's availability; each test here turns it on explicitly.
    """

    @staticmethod
    def _enable(app, monkeypatch, enabled=True):
        # app.config, not the Config class: the app is built once per session and
        # Flask copies the class attributes in at that point, so mutating the
        # class afterwards never reaches the running app.
        monkeypatch.setitem(app.config, "BREACH_CHECK_ENABLED", enabled)

    def test_registration_refuses_a_breached_password(self, client, app, monkeypatch):
        self._enable(app, monkeypatch)
        monkeypatch.setattr("routes.auth.is_breached", lambda *_a, **_k: True)

        res = client.post("/auth/register", json={
            "username": "alice", "password": "password",
        })
        assert res.status_code == 400
        assert "breach" in res.json["msg"].lower()
        assert "password" in res.json["errors"]

    def test_registration_allows_a_clean_password(self, client, app, monkeypatch):
        self._enable(app, monkeypatch)
        monkeypatch.setattr("routes.auth.is_breached", lambda *_a, **_k: False)

        res = client.post("/auth/register", json={
            "username": "alice", "password": "correct-horse-battery",
        })
        assert res.status_code == 201

    def test_the_check_can_be_turned_off(self, client, app, monkeypatch):
        self._enable(app, monkeypatch, enabled=False)

        def explode(*_args, **_kwargs):
            raise AssertionError("the breach check should not run when disabled")

        monkeypatch.setattr("routes.auth.is_breached", explode)
        res = client.post("/auth/register", json={
            "username": "alice", "password": "password",
        })
        assert res.status_code == 201

    def test_login_is_not_checked(self, client, app, monkeypatch):
        # The check belongs where a password is chosen. Running it on every login
        # would add a network round trip to the hot path.
        client.post("/auth/register", json={
            "username": "alice", "password": "correct-horse-battery",
        })

        self._enable(app, monkeypatch)

        def explode(*_args, **_kwargs):
            raise AssertionError("login must not perform a breach check")

        monkeypatch.setattr("routes.auth.is_breached", explode)
        res = client.post("/auth/login", json={
            "username": "alice", "password": "correct-horse-battery",
        })
        assert res.status_code == 200

    def test_a_rejected_reset_does_not_burn_the_token(self, client, app, monkeypatch):
        # The user should be able to retry the same link with a better password.
        client.post("/auth/register", json={
            "username": "alice", "password": "correct-horse-battery",
            "email": "alice@example.com",
        })
        client.post("/auth/login", json={
            "username": "alice", "password": "correct-horse-battery",
        })
        token = client.post("/account/verify-email/request").json["dev_token"]
        client.post("/account/verify-email/confirm", json={"token": token})
        client.post("/auth/logout")

        reset = client.post("/auth/forgot-password", json={"email": "alice@example.com"})
        raw = reset.json["dev_token"]

        self._enable(app, monkeypatch)
        monkeypatch.setattr("routes.auth.is_breached", lambda *_a, **_k: True)
        refused = client.post("/auth/reset-password", json={
            "token": raw, "password": "password",
        })
        assert refused.status_code == 400

        # Same link, better password: it must still work.
        monkeypatch.setattr("routes.auth.is_breached", lambda *_a, **_k: False)
        accepted = client.post("/auth/reset-password", json={
            "token": raw, "password": "a-much-better-password",
        })
        assert accepted.status_code == 200


def test_the_test_suite_never_reaches_the_network():
    """The suite must be hermetic.

    Found the hard way: BREACH_CHECK_ENABLED defaulted to True, every
    registration in the suite called the real API, and "correct-horse" is
    genuinely in the corpus, so tests failed for reasons that had nothing to do
    with the code under test.
    """
    from tests.conftest import TestConfig

    assert TestConfig.BREACH_CHECK_ENABLED is False


def test_every_test_local_config_also_disables_it():
    """A local config subclassing Config directly would re-enable the check."""
    import tests.test_client_ip as client_ip_tests
    import tests.test_ratelimit as ratelimit_tests
    from tests.conftest import TestConfig

    for config_class in (client_ip_tests._ProxyConfig, ratelimit_tests.LimitedConfig):
        assert config_class.BREACH_CHECK_ENABLED is False, (
            f"{config_class.__name__} would make its tests call the real API"
        )
        assert issubclass(config_class, TestConfig), (
            f"{config_class.__name__} should inherit the safe test defaults"
        )


def test_the_module_uses_no_third_party_dependency():
    # HIBP needs no key and no client library; if this ever imports requests or
    # a hashing package, the "no new dependency" property has been broken.
    import pathlib

    import breached

    source = pathlib.Path(breached.__file__).read_text(encoding="utf-8")
    for forbidden in ("import requests", "from passlib", "import bcrypt", "import argon2"):
        assert forbidden not in source
