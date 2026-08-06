from flask import Blueprint, request, jsonify
from models import User
from database import db

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.json

    user = User(username=data["username"])
    db.session.add(user)
    db.session.commit()

    return jsonify({"message": "user created"})