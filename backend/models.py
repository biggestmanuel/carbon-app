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

    # Reset tokens are stored hashed and single-use: the row is cleared the
    # moment the password changes.
    password_reset_token_hash = db.Column(db.String(64), nullable=True)
    password_reset_sent_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # Bumped on every password change. Tokens embed the value they were issued
    # with, so any older token is refused on its next request rather than
    # remaining valid until it expires.
    token_version = db.Column(db.Integer, nullable=False, default=1)

    footprints = db.relationship(
        "Footprint",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def set_password(self, password):
        # Force pbkdf2 so hash length is predictable and fits comfortably
        # in the column above (werkzeug's default scrypt hash can exceed
        # 128 chars and would otherwise get silently truncated).
        self.password_hash = generate_password_hash(password, method="pbkdf2:sha256")

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def matches_reset_token(self, raw_token, now=None):
        """True only if the token is present, unexpired, and correct."""
        if not self.reset_token_is_valid(now=now):
            return False
        return verify_token(raw_token, self.password_reset_token_hash)

    def to_dict(self):
        payload = {"id": self.id, "username": self.username}
        # Reveal only a masked address, and never the reset token hash.
        payload["has_email"] = bool(self.email)
        if self.email:
            payload["email"] = _mask_email(self.email)
        return payload

    def request_password_reset(self, token_hash, now=None):
        self.password_reset_token_hash = token_hash
        self.password_reset_sent_at = now or datetime.now(UTC)

    def reset_token_is_valid(self, now=None):
        if not self.password_reset_token_hash or not self.password_reset_sent_at:
            return False
        return not is_expired(self.password_reset_sent_at, now=now)

    def apply_new_password(self, password_hash):
        """Set the password, burn the reset token, and revoke live sessions.

        The version bump is what kills a refresh cookie stolen before the
        reset: it still parses, but no longer matches.
        """
        self.password_hash = password_hash
        self.password_reset_token_hash = None
        self.password_reset_sent_at = None
        self.token_version = (self.token_version or 1) + 1

    def __repr__(self):
        return f"<User {self.id} {self.username!r}>"


class Footprint(db.Model):
    __tablename__ = "footprint"

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
