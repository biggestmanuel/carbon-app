"""Password reset tokens.

Tokens are single-use, time-limited, and stored only as a hash. Storing the raw
value would mean a database leak hands over working reset links.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from werkzeug.security import check_password_hash, generate_password_hash

TOKEN_BYTES = 32
TOKEN_TTL = timedelta(minutes=30)

# Cost of verifying a token's hash. Low on purpose: these are already
# high-entropy random values, so the work factor buys nothing and costs latency.
_TOKEN_HASH_METHOD = "sha256"


def generate_token():
    """Return (raw_token, token_hash). Only the hash is ever persisted."""
    raw = secrets.token_urlsafe(TOKEN_BYTES)
    return raw, hash_token(raw)


def hash_token(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def verify_token(raw, stored_hash):
    if not raw or not stored_hash:
        return False
    # Constant-time comparison so a timing side channel cannot leak the hash.
    return secrets.compare_digest(hash_token(raw), stored_hash)


def is_expired(created_at, now=None):
    if created_at is None:
        return True
    now = now or datetime.now(UTC)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return now - created_at > TOKEN_TTL


def hash_password(password):
    # Force pbkdf2 for a predictable hash length, matching models.User.
    return generate_password_hash(password, method="pbkdf2:sha256")


def verify_password(stored_hash, password):
    if not stored_hash or not password:
        return False
    return check_password_hash(stored_hash, password)
