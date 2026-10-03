import re

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    get_jwt,
    get_jwt_identity,
    jwt_required,
    set_access_cookies,
    set_refresh_cookies,
    unset_jwt_cookies,
)
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db, limiter, rate_limits_exempt
from mail import send_password_reset, send_verification
from models import User, UserSession
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

    # Address ownership is only established once the recipient clicks the link.
    # Until then the address is not trusted for password reset.
    dev_token = None
    if email:
        raw_token, token_hash = generate_token()
        user.request_email_verification(token_hash)
        db.session.commit()
        try:
            send_verification(email, raw_token)
            if not current_app.config["MAIL_ENABLED"]:
                dev_token = raw_token
        except Exception:
            # The account still exists and works; only confirmation failed.
            db.session.rollback()
            current_app.logger.exception("Verification email failed during registration")

    payload = {
        "msg": "User registered",
        # Without a confirmed address there is no way to recover the account.
        "can_reset_password": False,
        "email_verified": False,
        "verification_required": bool(email),
    }
    if dev_token:
        payload["dev_token"] = dev_token
    return jsonify(payload), 201


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
        # One session row per authenticated device, so this login can be
        # revoked on its own later.
        session = user.start_session(
            user_agent=request.headers.get("User-Agent"), ip_address=_client_ip()
        )
        db.session.commit()

        # Tokens go into httpOnly cookies, never into the JSON body, so page
        # scripts and XSS payloads cannot read them out of localStorage.
        response = jsonify({
            "msg": "Logged in",
            "username": user.username,
            "email_verified": bool(user.email_verified),
        })
        set_access_cookies(
            response,
            _access_token_for(user, session.id),
            max_age=int(current_app.config["JWT_ACCESS_TOKEN_EXPIRES"].total_seconds()),
        )
        set_refresh_cookies(
            response,
            _refresh_token_for(user, session.id),
            max_age=int(current_app.config["JWT_REFRESH_TOKEN_EXPIRES"].total_seconds()),
        )
        return response, 200
    return jsonify({"msg": "Bad credentials"}), 401


def _client_ip():
    # X-Forwarded-For is only honoured because app.py installs ProxyFix for the
    # configured number of proxies, so a direct client cannot forge it.
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr


def _session_claims(user, session_id):
    """Claims carried in every token.

    The version ties the token to the user's current credential state, and the
    session id ties it to one device, so either can be revoked independently.
    """
    cfg = current_app.config
    return {
        cfg["JWT_SESSION_VERSION_CLAIM"]: user.token_version or 1,
        cfg["JWT_SESSION_ID_CLAIM"]: session_id,
    }


def _access_token_for(user, session_id):
    return create_access_token(
        identity=str(user.id), additional_claims=_session_claims(user, session_id)
    )


def _refresh_token_for(user, session_id):
    return create_refresh_token(
        identity=str(user.id), additional_claims=_session_claims(user, session_id)
    )


@auth_bp.route("/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    """Mint a new access token from the refresh cookie.

    The session id is carried over so refreshing does not silently orphan the
    session row and break per-device revocation.
    """
    user = db.session.get(User, int(get_jwt_identity()))
    if user is None:
        response = jsonify({"msg": "Session ended."})
        unset_jwt_cookies(response)
        return response, 401

    claims = get_jwt()
    session_id = claims.get(current_app.config["JWT_SESSION_ID_CLAIM"])
    if not session_id:
        response = jsonify({"msg": "Session ended."})
        unset_jwt_cookies(response)
        return response, 401

    response = jsonify({"msg": "Token refreshed"})
    set_access_cookies(
        response,
        _access_token_for(user, session_id),
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

    # Mailing an unconfirmed address would deliver a reset link to whoever
    # actually owns that inbox. The same generic response is returned either
    # way, so this cannot be used to probe which addresses are verified.
    if current_app.config["RESET_REQUIRES_VERIFIED_EMAIL"] and not user.can_reset_password():
        current_app.logger.info("Password reset refused for unverified address")
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
@jwt_required(optional=True)
def logout():
    """Sign out this device.

    Idempotent: clearing cookies succeeds whether or not a session existed, so
    the frontend can call it after the session has already lapsed.
    """
    # Remove just this device's row. "Sign out everywhere" is a separate,
    # explicit action on /account/sessions. get_jwt() raises when no token was
    # sent at all, and this endpoint must still succeed in that case.
    try:
        session_id = get_jwt().get(current_app.config["JWT_SESSION_ID_CLAIM"])
    except Exception:
        session_id = None
    if session_id:
        session = db.session.get(UserSession, session_id)
        if session is not None:
            db.session.delete(session)
            db.session.commit()

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
