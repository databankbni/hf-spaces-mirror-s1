from database import db

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True)

class Video(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200))
    filename = db.Column(db.String(200))

class Like(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.Integer)
    user_id = db.Column(db.Integer)

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.Integer)
    text = db.Column(db.String(300))