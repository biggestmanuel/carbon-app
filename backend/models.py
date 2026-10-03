from datetime import datetime, timezone

from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db


def _iso_utc(value):
    """ISO-8601 with an explicit offset.

    SQLite discards tzinfo even for DateTime(timezone=True), which would leave
    the frontend to guess the zone and silently shift every timestamp.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).isoformat()
    return value.astimezone(timezone.utc).isoformat()


class User(db.Model):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

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

    def to_dict(self):
        return {"id": self.id, "username": self.username}

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
    region = db.Column(db.String(16), nullable=False, default="world", index=True)
    factors_version = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
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
            "created_at": _iso_utc(self.created_at),
        }

    def __repr__(self):
        return f"<Footprint {self.id} user={self.user_id} total={self.total}>"