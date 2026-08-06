from flask import Flask, request, jsonify,send_file
from flask_cors import CORS

app=Flask(__name__)
CORS(app)

@app.route('/')
def index():
    return send_file("index.html")

@app.route('/style.css')
def css():
    return send_file("style.css")

@app.route('/script.js')
def script():
    return send_file('script.js')

@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json.get("message","")
    return jsonify({"response":f"you said:{user_message}"})

if __name__ == '__main__':
    app.run(host="0.0.0.0",port=7860)
    