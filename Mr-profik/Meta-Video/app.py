import os
from flask import Flask, jsonify, send_from_directory, request, render_template_string
from werkzeug.utils import secure_filename
from database import db
from models import Video

app = Flask(__name__)

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///metavideo.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

db.init_app(app)

# -------------------
# HTML САЙТ (как YouTube простая версия)
# -------------------
HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Meta Video</title>
</head>
<body>
    <h1>🎥 Meta Video</h1>

    <h2>📤 Upload</h2>
    <form action="/upload" method="post" enctype="multipart/form-data">
        <input type="text" name="title" placeholder="Title"><br><br>
        <input type="file" name="file"><br><br>
        <button type="submit">Upload</button>
    </form>

    <h2>📺 Videos</h2>
    <div id="videos"></div>

    <script>
        fetch("/api/feed")
        .then(r => r.json())
        .then(data => {
            let html = "";
            data.forEach(v => {
                html += `
                    <div style="margin-bottom:20px;">
                        <h3>${v.title}</h3>
                        <video width="300" controls>
                            <source src="${v.url}" type="video/mp4">
                        </video>
                    </div>
                `;
            });
            document.getElementById("videos").innerHTML = html;
        });
    </script>

</body>
</html>
"""

# -------------------
# ГЛАВНАЯ СТРАНИЦА
# -------------------
@app.route("/")
def home():
    return render_template_string(HTML)

# -------------------
# ЗАГРУЗКА ВИДЕО
# -------------------
@app.route("/upload", methods=["POST"])
def upload():
    file = request.files["file"]
    title = request.form.get("title", "Untitled")

    filename = secure_filename(file.filename)
    path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(path)

    video = Video(title=title, filename=filename)
    db.session.add(video)
    db.session.commit()

    return "Uploaded! Go back"

# -------------------
# FEED (список видео)
# -------------------
@app.route("/api/feed")
def feed():
    videos = Video.query.all()

    return jsonify([
        {
            "title": v.title,
            "url": f"/video/{v.filename}"
        }
        for v in videos
    ])

# -------------------
# СТРИМ ВИДЕО
# -------------------
@app.route("/video/<filename>")
def video(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

# -------------------
# START
# -------------------
if __name__ == "__main__":
    with app.app_context():
        db.create_all()

    port = int(os.environ.get("PORT", 7860))
    app.run(host="0.0.0.0", port=port)