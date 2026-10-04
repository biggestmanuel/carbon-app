"""Check a password against Have I Been Pwned's corpus of breaches.

Uses the k-anonymity range API: only the first five characters of the SHA-1
digest are sent, and the server returns every hash sharing that prefix. The
password itself, and the rest of its digest, never leave the machine, so there is
nothing to intercept and no API key to leak.

Fails open. If the network is down or the service is unreachable, the password is
allowed through and the failure is logged. A breach check that can lock every
existing user out of their own account during someone else's outage is worse than
no breach check at all.
"""

import hashlib
import logging
import urllib.error
import urllib.request

from flask import current_app

log = logging.getLogger(__name__)

API_ROOT = "https://api.pwnedpasswords.com/range"
PREFIX_LENGTH = 5


def sha1_prefix(password, length=PREFIX_LENGTH):
    """The leading hex characters of the password's SHA-1 digest."""
    digest = hashlib.sha1(password.encode("utf-8"), usedforsecurity=False).hexdigest()
    return digest[:length].upper()


def is_breached(password, timeout=2.0, fetch=None):
    """True when the password appears in the corpus.

    `fetch` is the seam the tests replace: a callable taking a URL and returning
    a context manager over the response body. Left None, it opens the real API.

    Returns False when the check is disabled, the service cannot be reached, or
    the response cannot be parsed. Anything other than a definite "yes" lets the
    password through.
    """
    if not password:
        return False

    prefix = sha1_prefix(password)
    open_url = fetch if fetch is not None else _make_fetcher(timeout)

    try:
        with open_url(f"{API_ROOT}/{prefix}") as response:
            body = response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        # Includes HTTPError, which is a subclass of URLError.
        log.warning("Breach check unavailable for prefix %s: %s", prefix, exc)
        return False

    suffix = sha1_prefix(password, length=40)[PREFIX_LENGTH:]
    for line in body.splitlines():
        candidate, _, _count = line.partition(":")
        # Constant-time is not needed: this is a public corpus, not a secret, and
        # the response is already the full answer set for this prefix.
        if candidate.strip().upper() == suffix:
            return True
    return False


def _make_fetcher(timeout):
    def _open(url):
        request = urllib.request.Request(
            url,
            # The API rejects requests without a user agent, and sending one is
            # also the polite thing to do to a free service.
            headers={"User-Agent": "carbon-app-breach-check", "Add-Padding": "true"},
        )
        # The URL is built from PREFIX_LENGTH hex characters, never from
        # anything a caller supplied, so the scheme and host are fixed.
        return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310

    return _open


def check_enabled():
    return bool(current_app.config.get("BREACH_CHECK_ENABLED", True))
