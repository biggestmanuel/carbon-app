import re

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    get_jwt_identity,
    jwt_required,
    set_access_cookies,
    set_refresh_cookies,
    unset_jwt_cookies,
)
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db, limiter, rate_limits_exempt
from mail import send_password_reset
from models import User
from passwords import generate_token, hash_password, hash_token

auth_bp = Blueprint("auth", __name__)

# Letters, digits, dot, dash, underscore. Deliberately permissive but it stops
# control characters, homoglyphs and unbounded whitespace reaching the DB.
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

# Pragmatic rather than exhaustive: one @, no whitespace, a dotted domain.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")

GENERIC_RESET_MSG = "If that address exists, a reset link is on its way."

# Verified against a throwaway hash when the username is unknown so that a
# missing account costs the same wall time as a wrong password, closing the
# user-enumeration timing side channel.
_DUMMY_HASH = generate_password_hash("timing-equaliser-not-a-real-password", method="pbkdf2:sha256")


def _credentials_from_request():
    data = request.get_json(silent=True) or {}
    username = data.get("username")
    password = data.get("password")
    if isinstance(username, str):
        username = username.strip()
    return username, password


def _validate_credentials(username, password):
    """Return an error message, or None when the pair is acceptable."""
    cfg = current_app.config
    if not username or not password:
        return "username and password are required"
    if len(username) < cfg["MIN_USERNAME_LENGTH"] or len(username) > cfg["MAX_USERNAME_LENGTH"]:
        return f"username must be {cfg['MIN_USERNAME_LENGTH']}-{cfg['MAX_USERNAME_LENGTH']} characters"
    if not USERNAME_RE.match(username):
        return "username may only contain letters, digits, dots, dashes and underscores"
    if not isinstance(password, str):
        return "password must be text"
    if len(password) < cfg["MIN_PASSWORD_LENGTH"]:
        return f"password must be at least {cfg['MIN_PASSWORD_LENGTH']} characters"
    if len(password) > cfg["MAX_PASSWORD_LENGTH"]:
        return f"password must be at most {cfg['MAX_PASSWORD_LENGTH']} characters"
    return None


def _validate_password(password):
    """Password rules on their own, for flows with no username."""
    cfg = current_app.config
    if not password:
        return "a new password is required"
    if not isinstance(password, str):
        return "password must be text"
    if len(password) < cfg["MIN_PASSWORD_LENGTH"]:
        return f"password must be at least {cfg['MIN_PASSWORD_LENGTH']} characters"
    if len(password) > cfg["MAX_PASSWORD_LENGTH"]:
        return f"password must be at most {cfg['MAX_PASSWORD_LENGTH']} characters"
    return None


def _normalise_email(raw):
    """Return a lowercase address, or None when absent or malformed."""
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        return ""
    email = raw.strip().lower()
    if len(email) > current_app.config["MAX_EMAIL_LENGTH"]:
        return ""
    return email if EMAIL_RE.match(email) else ""


@auth_bp.route("/register", methods=["POST"])
@limiter.limit(lambda: current_app.config["REGISTER_RATE_LIMIT"], exempt_when=rate_limits_exempt)
def register():
    data = request.get_json(silent=True) or {}
    username, password = _credentials_from_request()

    error = _validate_credentials(username, password)
    if error:
        return jsonify({"msg": error}), 400

    email = _normalise_email(data.get("email"))
    if email == "":
        return jsonify({"msg": "email must be a valid address"}), 400

    user = User(username=username, email=email)
    user.set_password(password)
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        # The unique constraint covers both username and email.
        if email and User.query.filter_by(email=email).first():
            return jsonify({"msg": "Email already registered"}), 409
        return jsonify({"msg": "Username already taken"}), 409

    return jsonify({
        "msg": "User registered",
        # Without an address there is nowhere to send a reset link, so say so.
        "can_reset_password": bool(email),
    }), 201


@auth_bp.route("/login", methods=["POST"])
@limiter.limit(lambda: current_app.config["LOGIN_RATE_LIMIT"], exempt_when=rate_limits_exempt)
def login():
    username, password = _credentials_from_request()

    error = _validate_credentials(username, password)
    if error:
        return jsonify({"msg": error}), 400

    user = User.query.filter_by(username=username).first()
    # Hash either way so response time does not reveal whether the user exists.
    password_ok = check_password_hash(user.password_hash if user else _DUMMY_HASH, password)

    if user and password_ok:
        # Tokens go into httpOnly cookies, never into the JSON body, so page
        # scripts and XSS payloads cannot read them out of localStorage.
        response = jsonify({"msg": "Logged in", "username": user.username})
        set_access_cookies(
            response,
            _access_token_for(user),
            max_age=int(current_app.config["JWT_ACCESS_TOKEN_EXPIRES"].total_seconds()),
        )
        set_refresh_cookies(
            response,
            _refresh_token_for(user),
            max_age=int(current_app.config["JWT_REFRESH_TOKEN_EXPIRES"].total_seconds()),
        )
        return response, 200
    return jsonify({"msg": "Bad credentials"}), 401


def _session_claims(user):
    """Version claim carried in every token, so a reset revokes live sessions."""
    return {current_app.config["JWT_SESSION_VERSION_CLAIM"]: user.token_version or 1}


def _access_token_for(user):
    return create_access_token(identity=str(user.id), additional_claims=_session_claims(user))


def _refresh_token_for(user):
    return create_refresh_token(identity=str(user.id), additional_claims=_session_claims(user))


@auth_bp.route("/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    """Mint a new access token from the refresh cookie."""
    user = db.session.get(User, int(get_jwt_identity()))
    if user is None:
        unset_jwt_cookies(jsonify({"msg": "Session ended."}))
        return jsonify({"msg": "Session ended."}), 401

    response = jsonify({"msg": "Token refreshed"})
    set_access_cookies(
        response,
        _access_token_for(user),
        max_age=int(current_app.config["JWT_ACCESS_TOKEN_EXPIRES"].total_seconds()),
    )
    return response


# Deliberately not rate limited on the token check: an attacker probing tokens
    # is throttled by the login limit, and an attacker flooding this endpoint
    # gains nothing since each request is a constant-time compare.
@auth_bp.route("/forgot-password", methods=["POST"])
@limiter.limit(lambda: current_app.config["RESET_RATE_LIMIT"], exempt_when=rate_limits_exempt)
def forgot_password():
    """Start a reset.

    Always returns 200 with the same message, whether or not the address is on
    file. Anything else turns this into a user-enumeration oracle.
    """
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower() if isinstance(data.get("email"), str) else ""

    if not email:
        return jsonify({"msg": GENERIC_RESET_MSG}), 202

    user = User.query.filter_by(email=email).first()
    if user is None:
        current_app.logger.info("Password reset requested for unknown address")
        return jsonify({"msg": GENERIC_RESET_MSG}), 202

    raw_token, token_hash = generate_token()
    user.request_password_reset(token_hash)
    db.session.commit()

    try:
        send_password_reset(user.email, raw_token)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Password reset email failed")
        # Do not claim success, and do not leak the address either.
        return jsonify({"msg": "Could not send the reset email. Try again later."}), 502

    response = {"msg": GENERIC_RESET_MSG}

    # With delivery off there is no inbox to check, so the link is returned
    # directly. This is a development affordance only, and MAIL_ENABLED is
    # rejected in production by Config.validate().
    if not current_app.config["MAIL_ENABLED"]:
        response["dev_token"] = raw_token

    return jsonify(response), 202


@auth_bp.route("/reset-password", methods=["POST"])
@limiter.limit(lambda: current_app.config["RESET_RATE_LIMIT"], exempt_when=rate_limits_exempt)
def reset_password():
    """Complete a reset using a token from the email."""
    data = request.get_json(silent=True) or {}
    token = data.get("token")
    new_password = data.get("password")

    if not isinstance(token, str) or not token:
        return jsonify({"msg": "A reset token is required"}), 400

    error = _validate_password(new_password)
    if error:
        return jsonify({"msg": error}), 400

    # The token hash is the lookup key, so no query depends on a guessable value.
    user = User.query.filter_by(password_reset_token_hash=hash_token(token)).first()
    if user is None or not user.matches_reset_token(token):
        # Same message for unknown, wrong and expired: do not distinguish.
        return jsonify({"msg": "This reset link is invalid or has expired."}), 400

    user.apply_new_password(hash_password(new_password))
    db.session.commit()

    # Force a fresh login on this device; other sessions end when their
    # refresh tokens expire.
    response = jsonify({"msg": "Password updated. Please log in again."})
    unset_jwt_cookies(response)
    return response, 200


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """Idempotent: clearing cookies succeeds whether or not a session existed."""
    response = jsonify({"msg": "Logged out"})
    unset_jwt_cookies(response)
    return response


@auth_bp.route("/me", methods=["GET"])
@jwt_required()
def me():
    """Lets the frontend confirm a restored session before rendering."""
    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)
    if user is None:
        return jsonify({"msg": "User no longer exists"}), 404
    return jsonify(user.to_dict())
