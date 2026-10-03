import os
from datetime import timedelta

# Secrets that must never reach production. Keeping them as named constants
# lets validate() recognise a placeholder instead of guessing.
_PLACEHOLDER_SECRETS = {
    "dev-only-insecure-secret-change-me-32ch",
    "dev-only-insecure-jwt-secret-change-me-32",
    "replace_with_generated_secret",
    "replace_with_another_generated_secret",
    "changeme", "secret", "dev_secret", "jwt_secret",
}


def _int_env(name, default, minimum=1):
    """Read an int from the environment, ignoring junk rather than crashing."""
    try:
        return max(minimum, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def _bool_env(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    ENV = os.environ.get("FLASK_ENV", "development")

    # Development-only fallbacks. validate() refuses to start in production
    # while these are in place, so they cannot leak to a real deploy.
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-insecure-secret-change-me-32ch")
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "dev-only-insecure-jwt-secret-change-me-32")

    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///carbon.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # --- Schema migrations -------------------------------------------------
    # create_all() cannot alter existing tables, so anything past local SQLite
    # goes through `flask db upgrade` instead. See AUTO_CREATE_TABLES below.
    MIGRATIONS_DIR = os.environ.get("MIGRATIONS_DIR", "migrations")
    AUTO_CREATE_TABLES = _bool_env("AUTO_CREATE_TABLES", False)

    # --- Sessions ----------------------------------------------------------
    # The access token lives in an httpOnly cookie, so page scripts cannot read
    # it and an XSS cannot exfiltrate it.
    JWT_TOKEN_LOCATION = ["cookies"]
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=_int_env("JWT_ACCESS_TOKEN_MINUTES", 30))
    JWT_COOKIE_SECURE = _bool_env("JWT_COOKIE_SECURE", ENV == "production")
    JWT_COOKIE_SAMESITE = os.environ.get("JWT_COOKIE_SAMESITE", "Lax")
    # csrf_protect stays off because every state-changing request is a JSON POST
    # from an allowlisted origin, which a cross-site form cannot forge and a
    # cross-origin fetch cannot pass CORS preflight for. Turn on if the API is
    # ever called from a context that allows those.
    JWT_COOKIE_CSRF_PROTECT = _bool_env("JWT_COOKIE_CSRF_PROTECT", False)
    # Rotating refresh cookie, so the 30 minute access token is not a hard stop.
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=_int_env("JWT_REFRESH_TOKEN_DAYS", 7))
    JWT_COOKIE_REFRESH_PROTECT = False

    # --- Browser access ----------------------------------------------------
    CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
    # Required for the browser to accept the auth cookie cross-origin. Safe only
    # because CORS_ORIGINS is an explicit allowlist and never "*".
    CORS_SUPPORTS_CREDENTIALS = True

    MAX_CONTENT_LENGTH = _int_env("MAX_CONTENT_LENGTH", 16 * 1024)  # 16 KB

    # --- Rate limiting -----------------------------------------------------
    # In-memory by default, which resets on restart and is not shared between
    # workers. Point this at Redis for any multi-process deployment.
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_ENABLED = _bool_env("RATELIMIT_ENABLED", True)
    RATELIMIT_HEADERS_ENABLED = True
    LOGIN_RATE_LIMIT = os.environ.get("LOGIN_RATE_LIMIT", "10 per minute")
    REGISTER_RATE_LIMIT = os.environ.get("REGISTER_RATE_LIMIT", "5 per hour")
    CALCULATE_RATE_LIMIT = os.environ.get("CALCULATE_RATE_LIMIT", "120 per minute")
    READ_RATE_LIMIT = os.environ.get("READ_RATE_LIMIT", "120 per minute")

    # --- Input limits, enforced in routes/footprint.py and routes/auth.py ---
    MIN_PASSWORD_LENGTH = _int_env("MIN_PASSWORD_LENGTH", 8)
    MAX_PASSWORD_LENGTH = 128  # bounds hashing cost against a huge-password DoS
    MIN_USERNAME_LENGTH = 3
    MAX_USERNAME_LENGTH = 80
    MAX_CAR_KM = 1_000_000.0
    MAX_ELECTRICITY_KWH = 1_000_000.0
    MAX_MEALS = 100_000

    @classmethod
    def validate(cls):
        """Fail loudly on unsafe configuration instead of silently defaulting."""
        problems = []
        if cls.ENV == "production":
            for name in ("SECRET_KEY", "JWT_SECRET_KEY"):
                value = getattr(cls, name)
                if not value or value in _PLACEHOLDER_SECRETS or len(value) < 32:
                    problems.append(f"{name} must be set to a unique 32+ character secret in production")
            if cls.AUTO_CREATE_TABLES:
                problems.append("AUTO_CREATE_TABLES must be off in production; use `flask db upgrade`")
            if not cls.JWT_COOKIE_SECURE:
                problems.append("JWT_COOKIE_SECURE must be on in production or the cookie travels over plain HTTP")
            if "*" in cls.CORS_ORIGINS:
                problems.append("CORS_ORIGINS cannot be '*' while cookies are enabled")
        if problems:
            raise RuntimeError("Unsafe configuration:\n  - " + "\n  - ".join(problems))