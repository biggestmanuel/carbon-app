"""Second factor: enrolment and code verification.

Split out from routes/auth.py and routes/account.py because these two flows have
different threat models and different blast radii.

The central design point is that a correct password alone never issues a
session. When TOTP is on, /auth/login returns a short-lived `mfa_pending` token
and no cookies; the session is minted only once a code has been verified against
that token. So a stolen password gets an attacker nothing but a five-minute
window and five guesses.

Two properties that are easy to get wrong and are pinned by tests:

- Every code-shaped string is checked against both the TOTP seed and the recovery
  codes before either is reported valid, so the response time and the status code
  do not distinguish the two paths.
- Turning 2FA off requires the password as well as a code. A second factor that
  can be removed by anyone holding the session it protects is not a second factor
  -- an attacker who phished the password would simply switch it off.
"""

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import create_access_token, decode_token, get_jwt_identity, jwt_required

from extensions import db, limiter, rate_limits_exempt
from mfa import (
    KeyUnavailable,
    encrypt,
    generate_recovery_codes,
    hash_recovery_code,
)
from models import RecoveryCode, User
from totp import counter_for_code, generate_secret, provisioning_uri, verify

mfa_bp = Blueprint("mfa", __name__)

# One message for everything: a wrong code, an expired pending token, a spent
# recovery code. Distinguishing them tells an attacker which half of a million
# possibilities they have already covered.
INVALID_CODE_MSG = "That code is not valid."


def _code_from_request():
    data = request.get_json(silent=True) or {}
    code = data.get("code")
    return code.strip() if isinstance(code, str) else ""


def _require_user():
    user = db.session.get(User, int(get_jwt_identity()))
    if user is None:
        return None, (jsonify({"msg": "User no longer exists"}), 404)
    return user, None


# --------------------------------------------------------------------------
# Verification (no session required -- the password step already happened)
# --------------------------------------------------------------------------


def verify_second_factor(user, code):
    """Spend `code` against this user, and say whether it worked.

    Returns "totp", "recovery" or None.

    Both paths are always attempted, in a fixed order, and the caller reports a
    single outcome either way. Checking the recovery codes only when the TOTP
    check fails would leak the path through timing: a recovery code has no
    matching HMAC, so it would return faster than any TOTP failure.
    """
    secret = user.totp_secret_plaintext()
    counter = counter_for_code(secret, code) if secret else None
    totp_ok = counter is not None

    # Replay guard. The stored counter only ever moves forward, so an
    # already-spent code from this window cannot be used again.
    if totp_ok and user.totp_last_counter is not None and counter <= user.totp_last_counter:
        totp_ok = False
        counter = None

    recovery = RecoveryCode.query.filter_by(
        user_id=user.id, code_hash=hash_recovery_code(code), used_at=None
    ).first() if code else None

    if totp_ok:
        user.consume_totp_counter(counter)
        return "totp"
    if recovery is not None and recovery.redeem():
        return "recovery"
    return None


@mfa_bp.route("/check", methods=["POST"])
@limiter.limit(
    lambda: current_app.config["TOTP_RATE_LIMIT"], exempt_when=rate_limits_exempt
)
def check_code():
    """Exchange a pending-login token plus a code for a real session."""
    data = request.get_json(silent=True) or {}
    pending = data.get("pending_token") or ""
    code = _code_from_request()

    claims = _decode_pending(pending)
    if claims is None:
        return jsonify({"msg": INVALID_CODE_MSG}), 401

    user = db.session.get(User, int(claims["sub"]))
    if user is None or not user.requires_totp():
        return jsonify({"msg": INVALID_CODE_MSG}), 401

    outcome = verify_second_factor(user, code)
    if outcome is None:
        return jsonify({"msg": INVALID_CODE_MSG}), 401

    # Issue the real session only now, reusing the login helper so there is one
    # place that knows how to mint cookies.
    from routes.auth import establish_session

    response = jsonify({
        "msg": "Logged in",
        "username": user.username,
        "email_verified": bool(user.email_verified),
        # Lets the UI show "signed in with a recovery code" instead of silently
        # pretending the authenticator was used.
        "second_factor": outcome,
    })
    establish_session(response, user, request)
    db.session.commit()
    return response, 200


def _decode_pending(token):
    """Claims from a pending-login token, or None when it is not usable."""
    if not isinstance(token, str) or not token:
        return None
    try:
        claims = decode_token(token)
    except Exception:
        # Includes expiry and signature failures. The caller must not learn which.
        return None
    if not claims.get("mfa_pending"):
        return None
    # A pending token must never carry a session id, or it could be replayed as
    # if it were a session credential.
    if claims.get(current_app.config["JWT_SESSION_ID_CLAIM"]):
        return None
    try:
        int(claims.get("sub"))
    except (TypeError, ValueError):
        return None
    return claims


# --------------------------------------------------------------------------
# Enrolment (session required)
# --------------------------------------------------------------------------


@mfa_bp.route("/start", methods=["GET"])
@jwt_required()
@limiter.limit(
    lambda: current_app.config["TOTP_MANAGE_RATE_LIMIT"], exempt_when=rate_limits_exempt
)
def start():
    """Begin enrolment and return the secret plus a provisioning URI.

    Deliberately does not require a password. The user is already authenticated,
    and demanding the password here would make the most common case -- adding 2FA
    while logged in on the device you are enrolling -- needlessly awkward.

    The secret is returned rather than stored pending confirmation, so a failed
    attempt leaves no half-enrolled state to reason about later.
    """
    user, failure = _require_user()
    if failure:
        return failure

    if user.requires_totp():
        return jsonify({"msg": "Two-factor authentication is already on."}), 409

    try:
        secret = generate_secret()
        # Encrypted and discarded. The point is to prove the key works *before*
        # the user scans anything: discovering at confirmation time that the
        # server cannot encrypt would mean they had just set up an authenticator
        # that cannot be stored, and would have to start again.
        encrypt(secret)
    except KeyUnavailable as exc:
        # Surfaced plainly rather than as a 500: this is a deployment problem
        # with a one-line fix, and the operator is the one who can make it.
        current_app.logger.error("TOTP enrolment unavailable: %s", exc)
        return jsonify({"msg": "Two-factor setup is not configured on this server."}), 503

    issuer = current_app.config["TOTP_ISSUER"]
    return jsonify({
        "secret": secret,
        "provisioning_uri": provisioning_uri(secret, user.username, issuer=issuer),
        "issuer": issuer,
        "digits": current_app.config["TOTP_DIGITS"],
        "period": current_app.config["TOTP_PERIOD_SECONDS"],
    }), 200


@mfa_bp.route("/confirm", methods=["POST"])
@jwt_required()
@limiter.limit(
    lambda: current_app.config["TOTP_MANAGE_RATE_LIMIT"], exempt_when=rate_limits_exempt
)
def confirm():
    """Switch 2FA on, proving the authenticator works, and issue recovery codes.

    Recovery codes are returned exactly once, here. Only hashes are stored, so
    they cannot be shown again -- the same trade the password reset link makes.
    """
    user, failure = _require_user()
    if failure:
        return failure

    data = request.get_json(silent=True) or {}
    secret = data.get("secret")
    code = _code_from_request()

    if not isinstance(secret, str) or not secret:
        return jsonify({"msg": "Start setup first."}), 400
    if not code:
        return jsonify({"msg": INVALID_CODE_MSG}), 401

    # The submitted code must prove the authenticator was set up correctly. This
    # is what stops someone enabling 2FA with a mistyped secret and locking
    # themselves out on the next login.
    if not verify(secret, code):
        return jsonify({"msg": INVALID_CODE_MSG}), 400

    try:
        user.enable_totp(encrypt(secret))
    except KeyUnavailable as exc:
        current_app.logger.error("TOTP confirmation unavailable: %s", exc)
        return jsonify({"msg": "Two-factor setup is not configured on this server."}), 503

    codes = generate_recovery_codes(current_app.config["TOTP_RECOVERY_CODES"])
    RecoveryCode.query.filter_by(user_id=user.id).delete()
    for code_value in codes:
        db.session.add(RecoveryCode(user_id=user.id, code_hash=hash_recovery_code(code_value)))
    db.session.commit()

    return jsonify({
        "msg": "Two-factor authentication is on.",
        "totp_enabled": True,
        # The only time these are ever sent.
        "recovery_codes": codes,
    }), 200


@mfa_bp.route("/disable", methods=["POST"])
@jwt_required()
@limiter.limit(
    lambda: current_app.config["TOTP_MANAGE_RATE_LIMIT"], exempt_when=rate_limits_exempt
)
def disable():
    """Turn 2FA off, then sign out everywhere.

    Revoking every session is the point. An attacker holding a refresh cookie that
    predates the change would otherwise keep access to an account whose owner has
    just enabled a second factor.
    """
    user, failure = _require_user()
    if failure:
        return failure

    if not user.requires_totp():
        return jsonify({"msg": "Two-factor authentication is not on."}), 409

    data = request.get_json(silent=True) or {}
    code = _code_from_request()
    password = data.get("password")

    if not code:
        return jsonify({"msg": INVALID_CODE_MSG}), 401

    # A current code proves the caller has the authenticator right now. The
    # password proves they are not relying on a stolen session alone.
    if verify_second_factor(user, code) is None:
        return jsonify({"msg": INVALID_CODE_MSG}), 401

    if (
        current_app.config["TOTP_DISABLE_REQUIRES_PASSWORD"]
        and (not isinstance(password, str) or not user.check_password(password))
    ):
        return jsonify({"msg": "Password is incorrect"}), 403

    user.disable_totp()
    db.session.commit()

    from flask_jwt_extended import unset_jwt_cookies

    response = jsonify({"msg": "Two-factor authentication is off.", "totp_enabled": False})
    unset_jwt_cookies(response)
    return response, 200


@mfa_bp.route("/recovery-codes", methods=["POST"])
@jwt_required()
def regenerate_recovery_codes():
    """Replace the recovery codes, invalidating the old set."""
    user, failure = _require_user()
    if failure:
        return failure

    if not user.requires_totp():
        return jsonify({"msg": "Two-factor authentication is not on."}), 409

    data = request.get_json(silent=True) or {}
    password = data.get("password")
    if not isinstance(password, str) or not user.check_password(password):
        # Generating a fresh set is how someone who has lost their codes gets
        # back in, so it is gated the same way as removing 2FA entirely.
        return jsonify({"msg": "Password is incorrect"}), 403

    codes = generate_recovery_codes(current_app.config["TOTP_RECOVERY_CODES"])
    RecoveryCode.query.filter_by(user_id=user.id).delete()
    for code_value in codes:
        db.session.add(RecoveryCode(user_id=user.id, code_hash=hash_recovery_code(code_value)))
    db.session.commit()

    return jsonify({"msg": "New recovery codes issued.", "recovery_codes": codes}), 200


@mfa_bp.route("/status", methods=["GET"])
@jwt_required()
def status():
    """Whether 2FA is on, and how many recovery codes are left."""
    user, failure = _require_user()
    if failure:
        return failure
    return jsonify({
        "totp_enabled": user.requires_totp(),
        "recovery_codes_remaining": user.recovery_codes_remaining(),
        "changed_at": user.totp_changed_at.isoformat() if user.totp_changed_at else None,
    }), 200


def create_pending_token(user):
    """A five-minute token proving the password step succeeded.

    Deliberately not a session: no `sid` claim, so it cannot be used against any
    authenticated endpoint, and the blocklist loader has no row to match it
    against.
    """
    return create_access_token(
        identity=str(user.id),
        additional_claims={
            "mfa_pending": True,
            current_app.config["JWT_SESSION_VERSION_CLAIM"]: user.token_version or 1,
        },
        expires_delta=_pending_lifetime(),
    )


def _pending_lifetime():
    from datetime import timedelta

    # Short on purpose. This token is a gap between two halves of one login, not a
    # session, and a longer life would give a password thief more attempts at the
    # six digits than the rate limit allows in one burst.
    return timedelta(minutes=5)
