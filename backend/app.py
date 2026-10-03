import os
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

    _register_error_handlers(app)

    from routes.auth import auth_bp
    from routes.footprint import footprint_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(footprint_bp, url_prefix="/footprint")

    # Dev escape hatch only. create_all() cannot alter existing tables, so the
    # normal path is `flask db upgrade`.
    if app.config["AUTO_CREATE_TABLES"]:
        with app.app_context():
            db.create_all()

    return app


def _register_error_handlers(app):
    @jwt.token_in_blocklist_loader
    def is_token_revoked(_header, payload):
        """Reject tokens issued before a password change.

        Checked on every request, so a session revoked by a password reset
        stops working immediately instead of lasting out the token lifetime.
        """
        from models import User

        version = payload.get(app.config["JWT_SESSION_VERSION_CLAIM"])
        try:
            user_id = int(payload.get("sub"))
        except (TypeError, ValueError):
            return True

        # Read only the two columns needed, without pulling in the whole row.
        row = db.session.execute(
            db.select(User.id, User.token_version).where(User.id == user_id)
        ).first()
        if row is None:
            return True
        return version != row.token_version

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
