"""RFC 6238 time-based one-time passwords.

Implemented directly on hmac, hashlib and struct rather than pulled in as a
package. Those three are stdlib, they are what the algorithm is defined in terms
of, and the whole of TOTP is a truncation of an HMAC over a counter -- there is
nothing here a dependency would be doing that is hard to get wrong, and an audit
trail that a six-digit code was checked against RFC 6238 is worth more than the
convenience.

What this module deliberately does not do:

- No account enumeration. A caller gets True or False for one submitted code and
  nothing else.
- No logging of codes.
- No accepting of a code from an arbitrarily distant window. The tolerance is a
  fixed one step either side, which covers clock drift between a phone and a
  server without turning the endpoint into an oracle for the seed.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

# RFC 4226 recommends 160 bits for the HMAC-SHA1 secret. Authenticator apps
# store this as base32 and show it as a 32-character string.
SECRET_BYTES = 20
# Enforced floor, matching the RFC 4226 recommendation. Anything shorter is
# refused rather than accepted with a warning, because a weak seed that verifies
# correctly looks exactly as valid as a strong one.
MIN_SECRET_BYTES = 20

DIGITS = 6
PERIOD = 30
ALGORITHM = "SHA1"
# One step either side. Wider windows are convenient and wrong: each extra step
# multiplies the number of live codes, and an attacker with a stolen database of
# encrypted seeds does not need many.
WINDOW = 1

BASE32_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"


def generate_secret(nbytes=SECRET_BYTES):
    """A fresh base32 secret, the form every authenticator app expects."""
    return base64.b32encode(secrets.token_bytes(nbytes)).decode("ascii").rstrip("=")


def normalise_secret(secret):
    """Tolerate the spacing and casing a human may have typed.

    Authenticator apps present the secret in groups of four separated by spaces,
    and users copy it with or without them, sometimes in lower case. Padding is
    restored because base32 decoding rejects a length that is not a multiple of
    eight.
    """
    if not secret:
        return ""
    cleaned = "".join(secret.split()).upper().replace("-", "")
    cleaned = cleaned.rstrip("=")
    padding = (-len(cleaned)) % 8
    return cleaned + "=" * padding


def decode_secret(secret):
    """The raw key bytes, or None when the secret is absent or not valid base32.

    None covers both "nothing configured" and "corrupted", because both mean the
    same thing to every caller: this cannot be used to verify a code. Returning
    b"" for an empty input would instead be truthy-adjacent in ways that are easy
    to get wrong at the call site.
    """
    normalised = normalise_secret(secret)
    if not normalised:
        return None
    try:
        key = base64.b32decode(normalised, casefold=True)
    except (ValueError, TypeError):
        return None
    # A secret shorter than the recommended 160 bits verifies codes perfectly
    # well, which is exactly the problem: it is trivially brute-forceable. Refuse
    # it outright rather than let a weak key in through a hand-typed secret.
    return key if len(key) >= MIN_SECRET_BYTES else None


def code_at(secret, counter, digits=DIGITS):
    """The HOTP value for one counter value (RFC 4226 section 5.3)."""
    key = decode_secret(secret)
    if not key:
        return None
    # Big-endian 8-byte counter. struct's > prefix is what makes this portable;
    # without it the value would differ per machine and codes would not match.
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    # Dynamic truncation: the low nibble of the last byte picks the offset of a
    # 4-byte window, whose top bit is masked off.
    offset = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[offset : offset + 4])[0]
    truncated &= 0x7FFFFFFF
    return str(truncated % (10**digits)).zfill(digits)


def current_counter(now=None):
    """Which time step `now` falls into."""
    timestamp = time.time() if now is None else now
    return int(timestamp // PERIOD)


def current_code(secret, now=None):
    """The code an authenticator is showing right now. Used by the tests."""
    return code_at(secret, current_counter(now))


def verify(secret, code, now=None, window=WINDOW):
    """True when `code` is valid for `secret` near `now`.

    Compared with hmac.compare_digest rather than `==`. A six-digit code is not
    a secret worth a timing attack in the abstract, but the comparison is free
    and this is the one place in the app where a constant-time compare is the
    obvious choice.
    """
    if not secret or not code:
        return False
    code = str(code).strip()
    # Reject anything that is not the right shape before doing HMAC work, and
    # refuse a leading-zero-stripped code so "12345" cannot satisfy "012345".
    if len(code) != DIGITS or not code.isdigit():
        return False

    counter = current_counter(now)
    for offset in range(-window, window + 1):
        candidate = code_at(secret, counter + offset)
        if candidate is not None and hmac.compare_digest(candidate, code):
            return True
    return False


def counter_for_code(secret, code, now=None, window=WINDOW):
    """The counter a verified code matched, or None.

    The caller records this so the same code cannot be replayed. A code is valid
    for up to three consecutive steps once the window is counted, and without
    remembering which step was spent, a code read off someone's shoulder stays
    usable for another 30 seconds.
    """
    if not secret or not code:
        return None
    code = str(code).strip()
    if len(code) != DIGITS or not code.isdigit():
        return None

    counter = current_counter(now)
    for offset in range(-window, window + 1):
        candidate = code_at(secret, counter + offset)
        if candidate is not None and hmac.compare_digest(candidate, code):
            return counter + offset
    return None


def provisioning_uri(secret, username, issuer="carbon-app"):
    """The otpauth:// URI an authenticator app reads from a QR code.

    The issuer is included because without it some apps label the entry with the
    bare account name, and a user with several services ends up unable to tell
    which is which.
    """
    if not secret or not username:
        return None
    label = quote(f"{issuer}:{username}", safe="")
    return (
        f"otpauth://totp/{label}"
        f"?secret={normalise_secret(secret).rstrip('=')}"
        f"&issuer={quote(issuer, safe='')}"
        f"&algorithm={ALGORITHM}"
        f"&digits={DIGITS}"
        f"&period={PERIOD}"
    )
