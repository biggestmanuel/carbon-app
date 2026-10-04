"""Account lifecycle: email verification, session management, export, deletion.

Kept separate from routes/auth.py because these are about the *account* rather
than the login handshake, and because deletion must never be reachable from a
stale session.
"""

import csv
import io
import json

from flask import Blueprint, Response, current_app, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required, unset_jwt_cookies
from sqlalchemy.exc import IntegrityError

from extensions import db, limiter, rate_limits_exempt
from mail import send_verification
from models import Footprint, User, UserSession
from passwords import generate_token, hash_token

account_bp = Blueprint("account", __name__)

GENERIC_VERIFY_MSG = "If that account exists, a confirmation link is on its way."


def _current_user():
    return db.session.get(User, int(get_jwt_identity()))


def _session_id_from_token():
    try:
        return get_jwt().get(current_app.config["JWT_SESSION_ID_CLAIM"])
    except Exception:
        return None


def _require_user():
    user = _current_user()
    if user is None:
        return None, (jsonify({"msg": "User no longer exists"}), 404)
    return user, None


def _client_ip():
    # Only trust X-Forwarded-For when a proxy is known to be setting it, which
    # is what ProxyFix below arranges. Otherwise a client could spoof it.
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr


# --------------------------------------------------------------------------
# Email verification
# --------------------------------------------------------------------------


@account_bp.route("/verify-email/request", methods=["POST"])
@jwt_required()
@limiter.limit(lambda: current_app.config["RESET_RATE_LIMIT"], exempt_when=rate_limits_exempt)
def request_verification():
    """Re-send a confirmation link. Requires a session, so it is not an oracle."""
    user, failure = _require_user()
    if failure:
        return failure

    if not user.email:
        return jsonify({"msg": "This account has no email address on file."}), 400
    if user.email_verified:
        return jsonify({"msg": "This address is already confirmed."}), 200

    raw_token, token_hash = generate_token()
    user.request_email_verification(token_hash)
    db.session.commit()

    try:
        send_verification(user.email, raw_token)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Verification email failed")
        return jsonify({"msg": "Could not send the confirmation email. Try again later."}), 502

    response = {"msg": GENERIC_VERIFY_MSG}
    if not current_app.config["MAIL_ENABLED"]:
        response["dev_token"] = raw_token
    return jsonify(response), 202


@account_bp.route("/verify-email/confirm", methods=["POST"])
@limiter.limit(lambda: current_app.config["RESET_RATE_LIMIT"], exempt_when=rate_limits_exempt)
def confirm_verification():
    """Confirm an address using the token from the email."""
    data = request.get_json(silent=True) or {}
    token = data.get("token")
    if not isinstance(token, str) or not token:
        return jsonify({"msg": "A confirmation token is required"}), 400

    user = User.query.filter_by(email_verification_token_hash=hash_token(token)).first()
    if user is None or not user.matches_verification_token(token):
        # Same message for unknown, wrong, expired and already-confirmed.
        return jsonify({"msg": "This confirmation link is invalid or has expired."}), 400

    user.mark_email_verified()
    db.session.commit()

    return jsonify({
        "msg": "Email confirmed. You can reset your password if you forget it.",
        "email_verified": True,
    }), 200


# --------------------------------------------------------------------------
# Session management
# --------------------------------------------------------------------------


@account_bp.route("/sessions", methods=["GET"])
@jwt_required()
def list_sessions():
    user, failure = _require_user()
    if failure:
        return failure

    current_id = _session_id_from_token()
    sessions = UserSession.query.filter_by(user_id=user.id).order_by(
        UserSession.last_seen_at.desc()
    ).all()
    return jsonify({"sessions": [s.to_dict(current_id) for s in sessions]})


@account_bp.route("/sessions/<session_id>", methods=["DELETE"])
@jwt_required()
def revoke_session(session_id):
    """Sign out one device. Revoking the current one clears this browser."""
    user, failure = _require_user()
    if failure:
        return failure

    # Scoped by user_id as well as the id, so one user cannot revoke another's
    # session by guessing a UUID.
    session = UserSession.query.filter_by(id=session_id, user_id=user.id).first()
    if session is None:
        return jsonify({"msg": "No such session"}), 404

    was_current = session.id == _session_id_from_token()
    db.session.delete(session)
    db.session.commit()

    response = jsonify({"msg": "Session revoked", "was_current": was_current})
    if was_current:
        unset_jwt_cookies(response)
    return response, 200


@account_bp.route("/sessions", methods=["DELETE"])
@jwt_required()
def revoke_all_sessions():
    """Sign out everywhere, including this device."""
    user, failure = _require_user()
    if failure:
        return failure

    user.revoke_sessions()
    # Bumping the version also invalidates any token issued before this call.
    user.token_version = (user.token_version or 1) + 1
    db.session.commit()

    response = jsonify({"msg": "Signed out everywhere"})
    unset_jwt_cookies(response)
    return response, 200


# --------------------------------------------------------------------------
# Data export and deletion
# --------------------------------------------------------------------------


@account_bp.route("/export", methods=["GET"])
@jwt_required()
def export_data():
    """Everything we hold about this account, as JSON or CSV."""
    user, failure = _require_user()
    if failure:
        return failure

    entries = Footprint.query.filter_by(user_id=user.id).order_by(Footprint.created_at.asc()).all()
    want_csv = request.args.get("format", "").lower() == "csv"

    if want_csv:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            ["id", "created_at", "region", "car_km", "electricity_kwh",
             "meat_meals", "plant_meals", "total_kg_co2e", "factors_version"]
        )
        for entry in entries:
            writer.writerow([
                entry.id,
                entry.to_dict()["created_at"],
                entry.region,
                entry.car_km,
                entry.electricity_kwh,
                entry.meat_meals,
                entry.plant_meals,
                round(entry.total, 4),
                entry.factors_version,
            ])
        return Response(
            buffer.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=carbon-footprint.csv"},
        )

    payload = {
        "exported_at": entries and entries[-1].to_dict()["created_at"],
        "account": user.to_dict(),
        "entry_count": len(entries),
        "entries": [e.to_dict() for e in entries],
    }
    return Response(
        json.dumps(payload, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=carbon-footprint.json"},
    )


@account_bp.route("/account", methods=["DELETE"])
@jwt_required()
@limiter.limit(lambda: current_app.config["DELETE_RATE_LIMIT"], exempt_when=rate_limits_exempt)
def delete_account():
    """Permanently delete the account and every footprint it owns.

    Requires the password again. A stolen session cookie must not be enough to
    destroy someone's history.
    """
    user, failure = _require_user()
    if failure:
        return failure

    data = request.get_json(silent=True) or {}
    password = data.get("password")
    if not isinstance(password, str) or not user.check_password(password):
        return jsonify({"msg": "Password is incorrect"}), 403

    # Clear the session before the row goes, so an in-flight request cannot
    # observe a half-deleted user. The relationship cascade would also do this,
    # but doing it explicitly keeps the intent obvious at the call site.
    user.revoke_sessions()
    db.session.delete(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        current_app.logger.exception("Account deletion failed")
        return jsonify({"msg": "Could not delete the account. Try again later."}), 500

    response = jsonify({"msg": "Account deleted"})
    unset_jwt_cookies(response)
    return response, 200
