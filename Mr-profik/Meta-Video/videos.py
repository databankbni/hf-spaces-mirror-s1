import os
from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename
from models import Video, Like, Comment
from database import db

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

videos_bp = Blueprint("videos", __name__)

# UPLOAD
@videos_bp.route("/upload", methods=["POST"])
def upload():
    file = request.files["file"]
    title = request.form.get("title", "Untitled")

    filename = secure_filename(file.filename)
    path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(path)

    video = Video(title=title, filename=filename)
    db.session.add(video)
    db.session.commit()

    return jsonify({"message": "uploaded"})

# FEED
@videos_bp.route("/feed")
def feed():
    videos = Video.query.all()

    return jsonify([
        {
            "id": v.id,
            "title": v.title,
            "url": f"/video/{v.filename}"
        }
        for v in videos
    ])

# LIKE
@videos_bp.route("/like/<int:video_id>")
def like(video_id):
    like = Like(video_id=video_id, user_id=1)
    db.session.add(like)
    db.session.commit()

    return jsonify({"message": "liked"})

# COMMENT
@videos_bp.route("/comment/<int:video_id>", methods=["POST"])
def comment(video_id):
    data = request.json

    c = Comment(video_id=video_id, text=data["text"])
    db.session.add(c)
    db.session.commit()

    return jsonify({"message": "comment added"})