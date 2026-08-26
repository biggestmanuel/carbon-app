from flask import Blueprint, request, jsonify
from sqlalchemy.exc import IntegrityError
from app import db
from models import User
from flask_jwt_extended import create_access_token

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"msg": "username and password are required"}), 400

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
def login():
    data = request.get_json(silent=True) or {}
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"msg": "username and password are required"}), 400

    user = User.query.filter_by(username=username).first()
    if user and user.check_password(password):
        # identity must be a string for recent flask-jwt-extended versions
        token = create_access_token(identity=str(user.id))
        return jsonify(access_token=token)
    return jsonify({"msg": "Bad credentials"}), 401
