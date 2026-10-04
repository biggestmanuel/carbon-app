"""Secret storage for TOTP.

The seed is stored encrypted rather than hashed, because hashing is not an option:
verification needs the original bytes, so a one-way function cannot be used. That
makes the column a plaintext-equivalent secret if it leaks, which is exactly what
the second factor exists to prevent -- an attacker holding the database could mint
valid codes for every account in it.

So the seed is encrypted at rest with Fernet (AES-128-CBC with an HMAC-SHA256
tag), keyed from TOTP_ENCRYPTION_KEY. A stolen database backup then yields
ciphertext, and the HMAC tag means a tampered ciphertext fails to decrypt rather
than producing a garbage seed that happens to verify against attacker-chosen
codes.

The key is deliberately separate from SECRET_KEY. Reusing one key for two jobs
means a bug in either can leak both, and rotating the session secret would
silently destroy every user's ability to log in.
"""

import base64
import secrets

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

from passwords import hash_token, verify_token


class KeyUnavailable(RuntimeError):
    """TOTP_ENCRYPTION_KEY is missing or unusable."""


def _fernet():
    key = current_app.config.get("TOTP_ENCRYPTION_KEY")
    if not key:
        raise KeyUnavailable(
            "TOTP_ENCRYPTION_KEY is not set, so TOTP secrets cannot be encrypted. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )
    try:
        return Fernet(key)
    except (ValueError, TypeError) as exc:
        raise KeyUnavailable("TOTP_ENCRYPTION_KEY is not a valid Fernet key") from exc


def available():
    """Whether secrets can be encrypted right now.

    Checked on the enable path so a misconfigured deployment fails at the point a
    user tries to switch 2FA on, with an actionable message, rather than storing
    an unencrypted seed and only discovering it later.
    """
    try:
        _fernet()
    except KeyUnavailable:
        return False
    return True


def encrypt(secret):
    """Encrypt a base32 TOTP secret for storage."""
    return _fernet().encrypt(secret.encode("utf-8")).decode("ascii")


def decrypt(token):
    """The base32 secret, or None when the ciphertext is absent or tampered.

    Returns None rather than raising for a decrypt failure: a corrupted row
    should refuse the login, not produce a 500 that tells an attacker their
    attempt reached an interesting code path.
    """
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        return None


def generate_recovery_codes(count=10):
    """Single-use codes for when the authenticator is lost.

    Ten bytes of entropy each, base32 without padding: 16 characters, no I/O/1
    ambiguity, and enough that guessing one against a stored hash is hopeless.

    Returned in plaintext exactly once. Only hashes are persisted, so there is no
    second chance to read them -- which is the same trade the password reset
    token makes, and for the same reason: a database leak must not hand over a
    working second factor.
    """
    codes = []
    while len(codes) < count:
        raw = secrets.token_bytes(10)
        code = base64.b32encode(raw).decode("ascii").rstrip("=")
        # Collisions are vanishingly unlikely but would silently produce a
        # duplicate in the set the user is given.
        if code not in codes:
            codes.append(code)
    return codes


def hash_recovery_code(code):
    """Hash a recovery code the same way reset tokens are hashed."""
    return hash_token(str(code).strip().upper())


def verify_recovery_code(code, stored_hash):
    return verify_token(str(code).strip().upper(), stored_hash)
