import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_cors import CORS

from config import Config
from extensions import db, jwt, limiter, migrate

BACKEND_DIR = Path(__file__).resolve().parent

# Resolve .env relative to this file instead of the process CWD, so the app
# still finds its config when launched from the repo root.
load_dotenv(BACKEND_DIR / ".env")


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)
    config_object.validate()

    db.init_app(app)
    jwt.init_app(app)
    migrate.init_app(app, db, directory=str(BACKEND_DIR / app.config["MIGRATIONS_DIR"]))
    limiter.init_app(app)

    # Credentialed CORS so the browser accepts the httpOnly auth cookie. Only
    # safe because CORS_ORIGINS is an explicit allowlist; Config.validate()
    # refuses to boot if it is ever set to "*".
    CORS(
        app,
        resources={r"/*": {"origins": app.config["CORS_ORIGINS"]}},
        supports_credentials=app.config["CORS_SUPPORTS_CREDENTIALS"],
    )

    # Behind a reverse proxy, TLS termination and the client IP both live in
    # headers the proxy sets. Trusting them blindly would let any client claim
    # https:// and forge its IP, so only honour them for the configured depth.
    if app.config["PROXY_FIX_X_FOR"]:
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=app.config["PROXY_FIX_X_FOR"],
            x_proto=app.config["PROXY_FIX_X_FOR"],
        )

    _register_error_handlers(app)
    _check_schema_is_current(app)

    from routes.account import account_bp
    from routes.auth import auth_bp
    from routes.footprint import footprint_bp
    from routes.mfa import mfa_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(account_bp, url_prefix="/account")
    app.register_blueprint(footprint_bp, url_prefix="/footprint")
    app.register_blueprint(mfa_bp, url_prefix="/auth/mfa")

    # Dev escape hatch only. create_all() cannot alter existing tables, so the
    # normal path is `flask db upgrade`.
    if app.config["AUTO_CREATE_TABLES"]:
        with app.app_context():
            db.create_all()

    return app


def _is_running_a_migration_command():
    """True when this process is the `flask db ...` CLI.

    The schema check below would otherwise be a chicken-and-egg problem: the
    command that *fixes* a stale database would be the one command refused
    because the database is stale.
    """
    return (
        "FLASK_RUN_FROM_CLI" in os.environ
        and len(sys.argv) > 1
        and sys.argv[1] == "db"
    )


def _check_schema_is_current(app):
    """Refuse to serve against a database the migrations have not reached.

    Found the hard way. AUTO_CREATE_TABLES is deliberately off, so an operator who
    pulls and forgets `flask db upgrade` gets a running app whose every request
    500s on `no such column: user.totp_secret` -- an error that names a column
    rather than the missing step, and appears only after deploying a migration.

    One cheap query at startup, compared against the migration head, turns a
    runtime failure across every endpoint into a refusal to boot with an
    instruction the operator can act on.
    """
    if not app.config.get("CHECK_SCHEMA_ON_STARTUP", True):
        return
    if _is_running_a_migration_command():
        return

    from alembic.script import ScriptDirectory
    from sqlalchemy import inspect, text
    from sqlalchemy.exc import SQLAlchemyError

    try:
        # Both the engine and Flask-Migrate's config need an application context,
        # which does not exist yet at this point in create_app().
        with app.app_context():
            head = ScriptDirectory.from_config(migrate.get_config()).get_current_head()
            # Asking whether the table exists, rather than catching the error from
            # selecting it, keeps "uninitialised" and "unreachable" apart. They
            # look alike in an exception and mean opposite things: the first is
            # fixed by `flask db upgrade`, the second by fixing the connection.
            if not inspect(db.engine).has_table("alembic_version"):
                applied = None
            else:
                with db.engine.connect() as connection:
                    applied = connection.execute(
                        text("SELECT version_num FROM alembic_version")
                    ).scalar()
    except SQLAlchemyError:
        # Cannot read the version because the database is unreachable or
        # misconfigured. That is a different failure with its own loud symptoms,
        # and refusing to boot here would replace a clear connection error with a
        # confusing one about the schema. The real error is on its way anyway.
        app.logger.exception(
            "Could not read the migration state; skipping the schema check. "
            "The database is probably unreachable."
        )
        return
    except Exception:
        # Our own problem with the migration directory rather than the database.
        app.logger.exception("Could not read the migration state")
        return

    if applied == head:
        return

    raise RuntimeError(
        "The database schema is out of date.\n"
        f"  applied: {applied or '(none)'}\n"
        f"  expected: {head or '(none)'}\n"
        "AUTO_CREATE_TABLES is off by design, so the schema only moves via Alembic. Run:\n"
        "    flask db upgrade\n"
        "and restart. Until then every request fails with a missing-column error."
    )


def _register_error_handlers(app):
    @jwt.token_in_blocklist_loader
    def is_token_revoked(_header, payload):
        """Accept a token only while its session is both current and alive.

        Two independent checks, because they cover different failures:

        - the version claim must match the user's, which kills every session at
          once after a password change;
        - the session id must still have a row, which is what lets one device be
          revoked without signing out the others.
        """
        from datetime import UTC, datetime, timedelta

        from models import User, UserSession

        version = payload.get(app.config["JWT_SESSION_VERSION_CLAIM"])
        try:
            user_id = int(payload.get("sub"))
        except (TypeError, ValueError):
            return True

        user = db.session.get(User, user_id)
        if user is None or version != (user.token_version or 1):
            return True

        session_id = payload.get(app.config["JWT_SESSION_ID_CLAIM"])
        if not session_id:
            # Covers a pending second-factor token. It is an access token so the
            # client can hold it, but it is not a session: carrying no sid means
            # it cannot be replayed against an authenticated endpoint, which is
            # the property routes/mfa.py relies on when it decodes one.
            return True
        session = db.session.get(UserSession, session_id)
        if session is None or session.user_id != user_id:
            return True

        # Refresh last_seen, but only occasionally: writing on every request
        # would turn each API call into a database update.
        interval = app.config["SESSION_TOUCH_INTERVAL_SECONDS"]
        now = datetime.now(UTC)
        seen = session.last_seen_at
        if seen is not None and seen.tzinfo is None:
            seen = seen.replace(tzinfo=UTC)
        if seen is None or now - seen > timedelta(seconds=interval):
            session.last_seen_at = now
            db.session.commit()

        return False

    @app.errorhandler(404)
    def handle_404(err):
        return jsonify({"msg": "Not found"}), 404

    @app.errorhandler(405)
    def handle_405(err):
        return jsonify({"msg": "Method not allowed"}), 405

    @app.errorhandler(413)
    def handle_413(err):
        return jsonify({"msg": "Request body too large"}), 413

    @app.errorhandler(500)
    def handle_500(err):
        # Never leak internals; the traceback stays in the server log.
        db.session.rollback()
        return jsonify({"msg": "Internal server error"}), 500

    @app.get("/health")
    def health():
        # Deliberately unthrottled. A load balancer or uptime monitor polling
        # this would get a 429 if the limit were ever reached, and may then pull
        # a perfectly healthy instance out of rotation -- a self-inflicted
        # outage in exchange for protecting a two-key JSON response.
        return jsonify({"status": "ok"})

    # flask-jwt-extended returns bare 401s by default. Normalise them so the
    # frontend can tell an expired token from a wrong password.
    @jwt.expired_token_loader
    def on_expired_token(_header, _payload):
        return (
            jsonify({"msg": "Session expired, please log in again", "code": "token_expired"}),
            401,
        )

    @jwt.invalid_token_loader
    def on_invalid_token(reason):
        return jsonify({"msg": "Invalid token", "code": "token_invalid", "detail": str(reason)}), 401

    @jwt.unauthorized_loader
    def on_missing_token(reason):
        return (
            jsonify({"msg": "Authentication required", "code": "token_missing", "detail": str(reason)}),
            401,
        )

    # Consistent JSON for throttled requests. Werkzeug already computes
    # Retry-After for TooManyRequests; the limiter sets the X-RateLimit-*
    # headers itself, so this only swaps the HTML body for JSON.
    @app.errorhandler(429)
    def handle_429(err):
        return jsonify({
            "msg": "Too many requests. Please slow down and try again shortly.",
            "code": "rate_limited",
        }), 429


app = create_app()

if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=int(os.environ.get("PORT", 5000)),
        debug=app.config["ENV"] == "development",
    )
