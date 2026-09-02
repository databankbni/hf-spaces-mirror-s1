import os
import sys
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from character_bot import MahabharataCharacter
import db
import json

load_dotenv()

app = Flask(__name__)

# Ensure the SQLite tables exist (idempotent) so a fresh deploy works.
db.init_db()

# Cache for active bots to avoid re-initializing
active_bots = {}

def get_bot(character_name, user_id):
    key = f"{user_id}_{character_name}"
    if key not in active_bots:
        active_bots[key] = MahabharataCharacter(character_name, user_id=user_id)
    return active_bots[key]

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/characters', methods=['GET'])
def get_characters():
    config_path = os.path.join(os.path.dirname(__file__), 'data', 'characters_config.json')
    try:
        with open(config_path, 'r') as f:
            data = json.load(f)
            # Return list of character names and their traits/styles for UI info
            characters = []
            for name, info in data.items():
                characters.append({
                    "name": name,
                    "traits": info.get("traits", ""),
                    "style": info.get("style", ""),
                    "values": info.get("values", "")
                })
            return jsonify(characters)
    except FileNotFoundError:
        return jsonify([])

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.json
    character_name = data.get('character')
    user_input = data.get('message')
    user_id = data.get('user_id', 'default_web_user')
    
    if not character_name or not user_input:
        return jsonify({"error": "Missing character or message"}), 400
        
    try:
        bot = get_bot(character_name, user_id)
        result = bot.chat(user_input)
        return jsonify({
            "response": result["response"],
            "sources": result.get("sources", [])
        })
    except Exception as e:
        print(f"Error in chat: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/history', methods=['GET'])
def history():
    character_name = request.args.get('character')
    user_id = request.args.get('user_id', 'default_web_user')
    
    if not character_name:
        return jsonify({"error": "Missing character"}), 400
        
    history = db.get_chat_history(user_id, character_name, limit=50)
    response = jsonify(history)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route('/api/clear_history', methods=['POST'])
def clear_history():
    data = request.json
    character_name = data.get('character')
    user_id = data.get('user_id', 'default_web_user')
    
    if not character_name:
        return jsonify({"error": "Missing character"}), 400
        
    success = db.clear_chat_history(user_id, character_name)
    if success:
        return jsonify({"message": "History cleared successfully"})
    else:
        return jsonify({"error": "Failed to clear history"}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
