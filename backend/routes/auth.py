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
from models import User

auth_bp = Blueprint("auth", __name__)

# Letters, digits, dot, dash, underscore. Deliberately permissive but it stops
# control characters, homoglyphs and unbounded whitespace reaching the DB.
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

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


@auth_bp.route("/register", methods=["POST"])
@limiter.limit(lambda: current_app.config["REGISTER_RATE_LIMIT"], exempt_when=rate_limits_exempt)
def register():
    username, password = _credentials_from_request()

    error = _validate_credentials(username, password)
    if error:
        return jsonify({"msg": error}), 400

    user = User(username=username)
    user.set_password(password)
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"msg": "Username already taken"}), 409

    return jsonify({"msg": "User registered"}), 201


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
            create_access_token(identity=str(user.id)),
            max_age=int(current_app.config["JWT_ACCESS_TOKEN_EXPIRES"].total_seconds()),
        )
        set_refresh_cookies(
            response,
            create_refresh_token(identity=str(user.id)),
            max_age=int(current_app.config["JWT_REFRESH_TOKEN_EXPIRES"].total_seconds()),
        )
        return response, 200
    return jsonify({"msg": "Bad credentials"}), 401


@auth_bp.route("/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    """Mint a new access token from the refresh cookie."""
    response = jsonify({"msg": "Token refreshed"})
    set_access_cookies(
        response,
        create_access_token(identity=get_jwt_identity()),
        max_age=int(current_app.config["JWT_ACCESS_TOKEN_EXPIRES"].total_seconds()),
    )
    return response


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
