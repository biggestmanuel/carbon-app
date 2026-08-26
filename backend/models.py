from app import db
from werkzeug.security import generate_password_hash, check_password_hash

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, password):
        # Force pbkdf2 so hash length is predictable and fits comfortably
        # in the column above (werkzeug's default scrypt hash can exceed
        # 128 chars and would otherwise get silently truncated).
        self.password_hash = generate_password_hash(password, method="pbkdf2:sha256")

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Footprint(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    car_km = db.Column(db.Float, default=0)
    electricity_kwh = db.Column(db.Float, default=0)
    meat_meals = db.Column(db.Integer, default=0)
    plant_meals = db.Column(db.Integer, default=0)
    total = db.Column(db.Float, default=0)
