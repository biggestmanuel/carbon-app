import math

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from extensions import db, limiter, rate_limits_exempt
from factors import (
    DEFAULT_REGION,
    catalogue,
    factors_for,
    is_valid_region,
    region_codes,
    snapshot,
)
from models import Footprint

footprint_bp = Blueprint("footprint", __name__)

# Which field is read from which emission factor and which config bound applies.
_INPUT_SPEC = {
    "car_km": ("car_km", "MAX_CAR_KM"),
    "electricity_kwh": ("electricity_kwh", "MAX_ELECTRICITY_KWH"),
    "meat_meals": ("meat_meal", "MAX_MEALS"),
    "plant_meals": ("plant_meal", "MAX_MEALS"),
}

# Meal counts are stored as integers, so reject fractions outright instead of
# truncating silently and storing a total that no longer adds up.
_WHOLE_NUMBER_FIELDS = {"meat_meals", "plant_meals"}


def _coerce(field, value, max_value):
    """Parse one field, rejecting anything that would poison the total."""
    if isinstance(value, bool) or value is None:
        return None, f"{field} must be a number"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None, f"{field} must be a number"

    # float("nan")/float("inf") pass every comparison below, which previously let
    # an NaN or Infinity total through and serialise as invalid JSON.
    if not math.isfinite(number):
        return None, f"{field} must be a finite number"
    # Emissions cannot be negative, but nothing stopped a -5000 km entry before.
    if number < 0:
        return None, f"{field} cannot be negative"
    if number > max_value:
        return None, f"{field} must be at most {max_value:g}"
    if field in _WHOLE_NUMBER_FIELDS and not number.is_integer():
        return None, f"{field} must be a whole number"
    return int(number) if field in _WHOLE_NUMBER_FIELDS else number, None


def _current_user_id():
    """Identity is stored as a string on login; cast it back for the FK."""
    try:
        return int(get_jwt_identity())
    except (TypeError, ValueError):
        return None


def _breakdown(values, factors):
    return {
        "car": values["car_km"] * factors["car_km"],
        "electricity": values["electricity_kwh"] * factors["electricity_kwh"],
        "meat": values["meat_meals"] * factors["meat_meal"],
        "plant": values["plant_meals"] * factors["plant_meal"],
    }


def _requested_region(data, key="region", fallback=DEFAULT_REGION):
    """Read and validate an optional region field, falling back when blank."""
    region = data.get(key)
    if region is None or region == "":
        return fallback, None
    if not isinstance(region, str) or not is_valid_region(region):
        return None, f"{key} must be one of: {', '.join(region_codes())}"
    return region, None


@footprint_bp.route("/calculate", methods=["POST"])
@jwt_required()
@limiter.limit(lambda: current_app.config["CALCULATE_RATE_LIMIT"], exempt_when=rate_limits_exempt)
def calculate():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"msg": "Request body must be a JSON object"}), 400

    cfg = current_app.config
    values, errors = {}, {}
    for field, (_, max_key) in _INPUT_SPEC.items():
        if field not in data:
            errors[field] = f"{field} is required"
            continue
        parsed, error = _coerce(field, data[field], cfg[max_key])
        if error:
            errors[field] = error
        else:
            values[field] = parsed

    # Where the electricity came from, and separately where the driving
    # happened. Blank travel_region means "same as home".
    region, region_error = _requested_region(data)
    if region_error:
        errors["region"] = region_error
    travel_region, travel_error = _requested_region(
        data, key="travel_region", fallback=region or DEFAULT_REGION
    )
    if travel_error:
        errors["travel_region"] = travel_error

    if errors:
        # Report every bad field at once instead of failing on the first.
        return jsonify({"msg": "; ".join(errors.values()), "errors": errors}), 400

    user_id = _current_user_id()
    if user_id is None:
        return jsonify({"msg": "Malformed token identity"}), 401

    factors = factors_for(region, travel_region)
    breakdown = _breakdown(values, factors)
    total = sum(breakdown.values())

    footprint = Footprint(
        user_id=user_id,
        total=total,
        region=factors["region"],
        factors_version=factors["factors_version"],
        # Snapshot the factors so a later table update cannot retroactively
        # change what an old entry means.
        factors_applied=snapshot(factors),
        **values,
    )
    db.session.add(footprint)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to persist footprint")
        return jsonify({"msg": "Could not save footprint"}), 500

    return jsonify({
        "id": footprint.id,
        "total": round(total, 4),
        "breakdown": {k: round(v, 4) for k, v in breakdown.items()},
        "inputs": values,
        "region": factors["region"],
        "travel_region": factors["travel_region"],
        "factors_version": factors["factors_version"],
        "factors_applied": snapshot(factors),
        "created_at": footprint.to_dict()["created_at"],
    }), 201


@footprint_bp.route("/factors", methods=["GET"])
def factors_catalogue():
    """Public so the form can label regions and show per-unit factors."""
    return jsonify(catalogue())


@footprint_bp.route("/history", methods=["GET"])
@jwt_required()
@limiter.limit(lambda: current_app.config["READ_RATE_LIMIT"], exempt_when=rate_limits_exempt)
def history():
    """Read path for the rows POST /calculate writes. Newest first, paged."""
    user_id = _current_user_id()
    if user_id is None:
        return jsonify({"msg": "Malformed token identity"}), 401

    try:
        limit = min(max(int(request.args.get("limit", 50)), 1), 200)
        offset = max(int(request.args.get("offset", 0)), 0)
    except (TypeError, ValueError):
        return jsonify({"msg": "limit and offset must be integers"}), 400

    query = Footprint.query.filter_by(user_id=user_id).order_by(
        Footprint.created_at.desc(), Footprint.id.desc()
    )
    total_entries = query.count()
    entries = query.offset(offset).limit(limit).all()

    return jsonify({
        "entries": [e.to_dict() for e in entries],
        "total_entries": total_entries,
        "limit": limit,
        "offset": offset,
    })


@footprint_bp.route("/summary", methods=["GET"])
@jwt_required()
@limiter.limit(lambda: current_app.config["READ_RATE_LIMIT"], exempt_when=rate_limits_exempt)
def summary():
    """Lifetime totals per category, so the dashboard can show more than one number."""
    user_id = _current_user_id()
    if user_id is None:
        return jsonify({"msg": "Malformed token identity"}), 401

    entries = Footprint.query.filter_by(user_id=user_id).all()
    if not entries:
        return jsonify({
            "entries": 0, "total": 0, "average": 0, "breakdown": {},
            "by_category": {}, "regions": [], "factors_versions": [],
        })

    totals = {
        "car_km": sum(e.car_km for e in entries),
        "electricity_kwh": sum(e.electricity_kwh for e in entries),
        "meat_meals": sum(e.meat_meals for e in entries),
        "plant_meals": sum(e.plant_meals for e in entries),
    }

    # Recompute the per-category split using each entry's own stored region.
    # Summing current factors across mixed regions would misreport the split,
    # so this walks the rows instead of applying one factor set.
    by_category = {"car": 0.0, "electricity": 0.0, "meat": 0.0, "plant": 0.0}
    for entry in entries:
        # Prefer the snapshot the row was written with, so an aggregate over old
        # history is not silently rescored by today's factor table. Fall back for
        # rows written before snapshots existed.
        factors = entry.factors_applied or snapshot(factors_for(entry.region))
        part = _breakdown(
            {
                "car_km": entry.car_km,
                "electricity_kwh": entry.electricity_kwh,
                "meat_meals": entry.meat_meals,
                "plant_meals": entry.plant_meals,
            },
            factors,
        )
        for key, value in part.items():
            by_category[key] += value

    grand_total = sum(e.total for e in entries)
    regions = sorted({e.region for e in entries})

    return jsonify({
        "entries": len(entries),
        "total": round(grand_total, 4),
        "average": round(grand_total / len(entries), 4),
        "breakdown": {k: round(v, 4) for k, v in by_category.items()},
        "by_category": totals,
        "regions": regions,
        # Reported so the client can tell the user that older entries were
        # scored with a different factor set than the current one.
        "factors_versions": sorted({e.factors_version for e in entries}),
    })
