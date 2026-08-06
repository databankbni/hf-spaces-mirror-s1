from flask import Blueprint, jsonify

mod_bp = Blueprint("mod", __name__)

@mod_bp.route("/ban/<int:user_id>")
def ban(user_id):
    return jsonify({"message": f"user {user_id} banned"})

@mod_bp.route("/delete/<int:video_id>")
def delete(video_id):
    return jsonify({"message": f"video {video_id} deleted"})