from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Held separately from app.py so models and routes can import them without a
# circular import through the application factory.
db = SQLAlchemy()
jwt = JWTManager()

# Schema history lives in ./migrations. create_all() can create missing tables
# but never alters existing ones, so real schema changes go through Alembic.
migrate = Migrate()

limiter = Limiter(
    key_func=get_remote_address,
    # Limits are declared per route with @limiter.limit(...). No global default,
    # so a newly added endpoint does not silently inherit a ceiling.
    default_limits=[],
    storage_uri="memory://",
)


def rate_limits_exempt():
    """Skip throttling when RATELIMIT_ENABLED is off.

    Flask-Limiter calls this per request, so current_app is available here.
    TESTING is deliberately not a trigger: the rate limit tests need throttling
    active, so they opt in by setting RATELIMIT_ENABLED rather than relying on
    a blanket test-mode exemption.
    """
    from flask import current_app

    return not current_app.config.get("RATELIMIT_ENABLED", True)