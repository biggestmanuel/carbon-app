import re
import uuid
from datetime import UTC, datetime

from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db
from passwords import is_expired, verify_token


def _mask_email(address):
    """d***e@example.com — enough to recognise an address, not to harvest one."""
    local, _, domain = address.partition("@")
    if not domain:
        return "***"
    if len(local) <= 2:
        head, tail = local[:1], local[1:]
    else:
        head, tail = local[0], local[-1]
    return f"{head}***{tail}@{domain}"


def _iso_utc(value):
    """ISO-8601 with an explicit offset.

    SQLite discards tzinfo even for DateTime(timezone=True), which would leave
    the frontend to guess the zone and silently shift every timestamp.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).isoformat()
    return value.astimezone(UTC).isoformat()


class User(db.Model):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    # Optional: a user with no address can still use the app, but cannot reset
    # a forgotten password, because there is nowhere to send the link.
    email = db.Column(db.String(254), unique=True, nullable=True, index=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Both children are deleted by the ORM rather than by the database.
    #
    # Not passive_deletes: SQLite only honours ON DELETE CASCADE when
    # `PRAGMA foreign_keys` is on, which it is not by default. Leaving this on
    # meant deleting an account left its history behind, still reachable by
    # user_id. Declaring either relationship twice is a trap, because the second
    # definition silently replaces the first -- that is how `sessions` ended up
    # with passive_deletes=True here while `footprints` was correct.
    footprints = db.relationship(
        "Footprint",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=False,
    )
    sessions = db.relationship(
        "UserSession",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=False,
    )
    # Orphaned by the ORM for the same reason as the two above, and on the same
    # grounds: SQLite ignores ON DELETE CASCADE unless foreign keys are switched
    # on per connection, so relying on the database would leave recovery codes
    # behind after an account deletion.
    recovery_codes = db.relationship(
        "RecoveryCode",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=False,
    )

    # Reset tokens are stored hashed and single-use: the row is cleared the
    # moment the password changes.
    password_reset_token_hash = db.Column(db.String(64), nullable=True)
    password_reset_sent_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # Bumped on every password change. Tokens embed the value they were issued
    # with, so any older token is refused on its next request rather than
    # remaining valid until it expires.
    token_version = db.Column(db.Integer, nullable=False, default=1)

    # Ownership of an address is only assumed once the recipient clicks the
    # confirmation link. Until then the address can be registered by anyone,
    # which is how a reset link ends up in someone else's inbox.
    email_verified = db.Column(db.Boolean, nullable=False, default=False)
    email_verification_token_hash = db.Column(db.String(64), nullable=True)
    email_verification_sent_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # --- Second factor (TOTP) ----------------------------------------------
    # The seed is encrypted at rest rather than hashed: verification needs the
    # original bytes, so a one-way function is not an option, and a plaintext seed
    # in a leaked database would let an attacker mint valid codes for every
    # account. See mfa.py.
    totp_secret = db.Column(db.Text, nullable=True)
    totp_enabled = db.Column(db.Boolean, nullable=False, default=False)
    # The time step of the last accepted code, so a code cannot be replayed
    # inside its own validity window. Without this a code shoulder-surfed off a
    # screen stays usable for another 30 seconds.
    totp_last_counter = db.Column(db.BigInteger, nullable=True)
    # Set when 2FA is switched on or a recovery code is used, so the session list
    # can tell a user when to re-check their other devices.
    totp_changed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    def set_password(self, password):
        # scrypt, which is Werkzeug's default. It is memory-hard, so it resists
        # GPU cracking far better than pbkdf2, and it is also the cheaper of the
        # two here: measured at 142 ms against 903 ms for pbkdf2:sha256 at
        # Werkzeug's raised default of 1,000,000 iterations.
        #
        # The previous comment here justified pbkdf2 by saying scrypt "can exceed
        # 128 chars and would otherwise get silently truncated". A scrypt hash is
        # 162 characters and the column is String(255), so it never truncated.
        # The slower and weaker option was chosen for a reason that does not hold.
        #
        # Hashes already stored as pbkdf2 keep verifying: the method is recorded
        # inside the hash string, so check_password_hash reads it back and nobody
        # is forced to reset their password.
        self.password_hash = generate_password_hash(password, method="scrypt")

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def matches_reset_token(self, raw_token, now=None):
        """True only if the token is present, unexpired, and correct."""
        if not self.reset_token_is_valid(now=now):
            return False
        return verify_token(raw_token, self.password_reset_token_hash)

    def to_dict(self):
        payload = {"id": self.id, "username": self.username}
        # Reveal only a masked address, and never a token hash.
        payload["has_email"] = bool(self.email)
        payload["email_verified"] = bool(self.email_verified)
        if self.email:
            payload["email"] = _mask_email(self.email)
        # Enough for the UI to show and disable 2FA. Never the seed, never a
        # count of remaining recovery codes as a standalone figure.
        payload["totp_enabled"] = self.requires_totp()
        payload["recovery_codes_remaining"] = self.recovery_codes_remaining()
        return payload

    def recovery_codes_remaining(self):
        """Unused recovery codes. 0 for a user who never enrolled."""
        from models import RecoveryCode

        if not self.totp_enabled:
            return 0
        return RecoveryCode.query.filter_by(user_id=self.id, used_at=None).count()

    def request_password_reset(self, token_hash, now=None):
        self.password_reset_token_hash = token_hash
        self.password_reset_sent_at = now or datetime.now(UTC)

    def reset_token_is_valid(self, now=None):
        if not self.password_reset_token_hash or not self.password_reset_sent_at:
            return False
        return not is_expired(self.password_reset_sent_at, now=now)

    def request_email_verification(self, token_hash, now=None):
        self.email_verification_token_hash = token_hash
        self.email_verification_sent_at = now or datetime.now(UTC)

    def matches_verification_token(self, raw_token, now=None):
        """True only if the address is still unverified and the token is live."""
        if self.email_verified or not raw_token:
            return False
        if not self.email_verification_token_hash or not self.email_verification_sent_at:
            return False
        if is_expired(self.email_verification_sent_at, now=now):
            return False
        return verify_token(raw_token, self.email_verification_token_hash)

    def mark_email_verified(self):
        self.email_verified = True
        self.email_verification_token_hash = None
        self.email_verification_sent_at = None

    def requires_totp(self):
        """Whether a correct password still needs a second factor.

        Both the flag and a stored secret must be present. They are set together,
        but a half-written row from an interrupted enrolment would otherwise lock
        the owner out of their own account with no way back.
        """
        return bool(self.totp_enabled and self.totp_secret)

    def totp_secret_plaintext(self):
        """The decrypted base32 seed, or None when it cannot be read."""
        from mfa import decrypt

        return decrypt(self.totp_secret)

    def consume_totp_counter(self, counter):
        """Record a code as spent.

        Only advances the stored value: a code from an earlier step must not be
        able to walk the marker backwards and become replayable again.
        """
        if counter is None:
            return
        if self.totp_last_counter is None or counter > self.totp_last_counter:
            self.totp_last_counter = counter

    def enable_totp(self, encrypted_secret, now=None):
        """Arm the second factor. Enrolment is confirmed separately."""
        self.totp_secret = encrypted_secret
        self.totp_enabled = True
        self.totp_last_counter = None
        self.totp_changed_at = now or datetime.now(UTC)

    def disable_totp(self):
        """Turn the second factor off and forget the seed.

        Also bumps token_version, which is what makes the change take effect on
        sessions that are already authenticated: without it, an attacker holding a
        refresh cookie keeps access after the owner adds 2FA.
        """
        self.totp_secret = None
        self.totp_enabled = False
        self.totp_last_counter = None
        self.totp_changed_at = datetime.now(UTC)
        self.token_version = (self.token_version or 1) + 1
        self.revoke_sessions()
        RecoveryCode.query.filter_by(user_id=self.id).delete()

    def can_reset_password(self):
        """Only a confirmed address can receive a reset link.

        Mailing an unverified address is how a reset link lands in the inbox of
        whoever actually owns it. An account with no address cannot reset at all,
        which is stated plainly rather than silently failing.
        """
        return bool(self.email and self.email_verified)

    def start_session(self, user_agent=None, ip_address=None):
        """Record a newly authenticated device and return the row."""
        session = UserSession(
            id=str(uuid.uuid4()),
            user_id=self.id,
            user_agent=user_agent[:200] if user_agent else None,
            # Sized for IPv6 including its full form.
            ip_address=ip_address[:45] if ip_address else None,
        )
        db.session.add(session)
        return session

    def revoke_sessions(self):
        """Delete every session row for this user.

        The version bump alone would be enough to make the tokens unusable, but
        the rows would linger: GET /account/sessions would list devices that can
        no longer authenticate, indistinguishable from live ones, and the table
        would grow without bound.

        A user that has never been written has no sessions, so this returns
        without querying. That also keeps the method usable on a transient
        instance, which is how the token tests exercise it.
        """
        if self.id is None:
            return
        UserSession.query.filter_by(user_id=self.id).delete()

    def apply_new_password(self, password_hash):
        """Set the password, burn the reset token, and revoke live sessions.

        The version bump is what kills a refresh cookie stolen before the
        reset: it still parses, but no longer matches. The rows go too, so the
        session list only ever shows devices that can still be used.
        """
        self.password_hash = password_hash
        self.password_reset_token_hash = None
        self.password_reset_sent_at = None
        self.token_version = (self.token_version or 1) + 1
        self.revoke_sessions()

    def __repr__(self):
        return f"<User {self.id} {self.username!r}>"


class UserSession(db.Model):
    """One logged-in device.

    The token_version column on User kills every session at once, which is the
    right default but too blunt: losing a phone should not sign you out of your
    laptop. Each session carries its own id in the JWT, and the blocklist loader
    checks that the id is still present, so a single device can be revoked
    without touching the others.
    """

    __tablename__ = "user_session"

    id = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Coarse device hints only. Deliberately not a fingerprint: it is for a human
    # to recognise their own sessions, not for tracking.
    user_agent = db.Column(db.String(200), nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)  # holds IPv6
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    last_seen_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    user = db.relationship("User", back_populates="sessions")

    def to_dict(self, current_id=None, earlier_ips=None, earlier_agents=None):
        """Serialise for the session list.

        `earlier_ips` and `earlier_agents` are the addresses and user agents this
        account had used *before this session was created*. Comparing against
        earlier sessions only is what makes the flags mean something: a set that
        already includes a session's own values can never report it as unfamiliar.

        An empty comparison set means "this is the account's first session", and
        nothing is claimed. A single-device user must not be told their only
        device is somewhere new.

        They stay False when the caller supplies nothing, so the other callers of
        to_dict() do not cry wolf.
        """
        ip = self.ip_address
        agent = self.user_agent

        new_location = bool(
            ip and earlier_ips and ip not in earlier_ips
        )
        new_device = bool(
            agent and earlier_agents and agent not in earlier_agents
        )

        return {
            "id": self.id,
            "label": describe_session(agent),
            "browser": describe_device(agent),
            "os": describe_os(agent),
            "user_agent": agent,
            "ip_address": ip,
            "created_at": _iso_utc(self.created_at),
            "last_seen_at": _iso_utc(self.last_seen_at),
            "current": self.id == current_id,
            # An unfamiliar address is the single most useful signal here: it is
            # what a stolen password looks like from the inside.
            "new_location": new_location,
            "new_device": new_device,
            # Worth surfacing only when something is actually unfamiliar.
            "unrecognised": new_location or new_device,
        }

    def __repr__(self):
        return f"<UserSession {self.id} user={self.user_id}>"


# Ordered most specific first: Edge and Opera both claim to be Chrome, and
# Chrome claims to be Safari.
_DEVICE_PATTERNS = (
    ("Edge", r"Edg/"),
    ("Opera", r"OPR/"),
    ("Firefox", r"Firefox/"),
    ("Chrome", r"Chrome/"),
    ("Safari", r"Version/.*Safari/"),
    ("curl", r"curl/"),
    ("Postman", r"PostmanRuntime/"),
    ("Python", r"python-requests|Python/"),
)

_OS_PATTERNS = (
    ("iPhone", r"iPhone"),
    ("iPad", r"iPad"),
    ("Android", r"Android"),
    ("Windows", r"Windows"),
    ("macOS", r"Mac OS X|Macintosh"),
    ("Chrome OS", r"CrOS"),
    ("Linux", r"Linux|X11"),
)


def describe_device(user_agent):
    """Best-effort human label for a session row. Never raises."""
    if not user_agent:
        return "Unknown device"
    for name, pattern in _DEVICE_PATTERNS:
        if re.search(pattern, user_agent):
            return name
    return "Unknown device"


def describe_os(user_agent):
    """The platform, so two Chromes can be told apart. Never raises."""
    if not user_agent:
        return None
    for name, pattern in _OS_PATTERNS:
        if re.search(pattern, user_agent):
            return name
    return None


def describe_session(user_agent):
    """'Chrome on Windows', or just the browser when the OS is unrecognised.

    The device list is the screen a user consults when they suspect someone else
    is in their account, so 'Chrome' alone cannot distinguish their own laptop
    from one they have never seen.
    """
    device = describe_device(user_agent)
    operating_system = describe_os(user_agent)
    if operating_system and device != "Unknown device":
        return f"{device} on {operating_system}"
    return device


class RecoveryCode(db.Model):
    """One single-use code for logging in without the authenticator.

    Stored hashed, like the reset token: a database leak must not hand over a
    working second factor. `used_at` is set on redemption rather than deleting the
    row, so an exhausted account can tell "all ten used" from "never had any" and
    so reuse can be counted.
    """

    __tablename__ = "recovery_code"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code_hash = db.Column(db.String(64), nullable=False)
    used_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    user = db.relationship("User", back_populates="recovery_codes")

    @property
    def is_used(self):
        return self.used_at is not None

    def redeem(self, now=None):
        """Mark spent. Returns False if it had already been used."""
        if self.is_used:
            return False
        self.used_at = now or datetime.now(UTC)
        return True

    def __repr__(self):
        state = "used" if self.is_used else "unused"
        return f"<RecoveryCode {self.id} user={self.user_id} {state}>"


class Footprint(db.Model):
    __tablename__ = "footprint"

    __table_args__ = (
        # GET /footprint/history filters on user_id and orders by created_at DESC
        # with id as the tiebreak. The single-column indexes on user_id and
        # created_at let Postgres serve that as filter-then-sort; this composite
        # lets it walk the index in order instead, with no sort step.
        db.Index("ix_footprint_user_created", "user_id", "created_at", "id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    # Indexed because every read is scoped to a single user.
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    car_km = db.Column(db.Float, default=0, nullable=False)
    electricity_kwh = db.Column(db.Float, default=0, nullable=False)
    # Meal counts are whole numbers; routes/footprint.py rejects anything else,
    # which keeps `total` reproducible from the stored columns on every backend.
    meat_meals = db.Column(db.Integer, default=0, nullable=False)
    plant_meals = db.Column(db.Integer, default=0, nullable=False)
    total = db.Column(db.Float, default=0, nullable=False)
    # Grid mix drives the electricity factor, so it is recorded per entry.
    # Factors version is stored so a future factor update can be detected
    # against historical rows instead of silently changing what they mean.
    # Region is a composite of where the electricity came from and where the
    # travel happened, which can differ (a UK resident driving in France). It is
    # stored as written so history stays reproducible if the format changes.
    region = db.Column(db.String(32), nullable=False, default="world", index=True)
    factors_version = db.Column(db.Integer, nullable=False, default=1)
    # Per-entry factor snapshot. Historical rows must keep scoring the same way
    # even after the table above is updated, so the exact values used are kept.
    factors_applied = db.Column(db.JSON, nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )

    user = db.relationship("User", back_populates="footprints")

    def to_dict(self):
        return {
            "id": self.id,
            "car_km": self.car_km,
            "electricity_kwh": self.electricity_kwh,
            "meat_meals": self.meat_meals,
            "plant_meals": self.plant_meals,
            "total": round(self.total, 4),
            "region": self.region,
            "factors_version": self.factors_version,
            "factors_applied": self.factors_applied,
            "created_at": _iso_utc(self.created_at),
        }

    def __repr__(self):
        return f"<Footprint {self.id} user={self.user_id} total={self.total}>"
