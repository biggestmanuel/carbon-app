from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app import db
from models import Footprint

footprint_bp = Blueprint("footprint", __name__)

emission_factors = {
    "car_km": 0.21,
    "electricity_kwh": 0.5,
    "meat_meal": 5.0,
    "plant_meal": 2.0
}

@footprint_bp.route("/calculate", methods=["POST"])
@jwt_required()
def calculate():
    data = request.get_json(silent=True) or {}
    required_fields = ["car_km", "electricity_kwh", "meat_meals", "plant_meals"]

    missing = [f for f in required_fields if f not in data]
    if missing:
        return jsonify({"msg": f"Missing fields: {', '.join(missing)}"}), 400

    try:
        car_km = float(data["car_km"])
        electricity_kwh = float(data["electricity_kwh"])
        meat_meals = float(data["meat_meals"])
        plant_meals = float(data["plant_meals"])
    except (TypeError, ValueError):
        return jsonify({"msg": "All fields must be numbers"}), 400

    total = (car_km * emission_factors["car_km"] +
             electricity_kwh * emission_factors["electricity_kwh"] +
             meat_meals * emission_factors["meat_meal"] +
             plant_meals * emission_factors["plant_meal"])

    footprint = Footprint(
        # identity was stored as a string on login; cast back to int for the FK
        user_id=int(get_jwt_identity()),
        car_km=car_km,
        electricity_kwh=electricity_kwh,
        meat_meals=meat_meals,
        plant_meals=plant_meals,
        total=total
    )
    db.session.add(footprint)
    db.session.commit()

    return jsonify({"total": total})
