import os
from flask import Blueprint, request, jsonify
from models import Video
from database import db

upload_bp = Blueprint("upload", __name__)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@upload_bp.route("/", methods=["POST"])
def upload():
    file = request.files["file"]
    title = request.form.get("title")

    path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(path)

    video = Video(title=title, filename=file.filename)
    db.session.add(video)
    db.session.commit()

    return jsonify({"message": "uploaded"})