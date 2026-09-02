import os
import sqlite3
import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'mahabharata_chat.db')
HISTORY_DIR = os.path.join(os.path.dirname(__file__), 'chat_history')

def migrate():
    if not os.path.exists(DB_PATH):
        print("Database not found.")
        return

    if not os.path.exists(HISTORY_DIR):
        os.makedirs(HISTORY_DIR)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Get all sessions
    c.execute("SELECT id, user_id, character_name FROM sessions")
    sessions = c.fetchall()

    print(f"Found {len(sessions)} sessions.")

    for session_id, user_id, character_name in sessions:
        filename = f"{character_name}_{user_id}.txt"
        filepath = os.path.join(HISTORY_DIR, filename)
        
        # Get messages for this session
        c.execute("SELECT role, content, timestamp FROM messages WHERE session_id = ? ORDER BY timestamp ASC", (session_id,))
        messages = c.fetchall()
        
        with open(filepath, 'w', encoding='utf-8') as f:
            for role, content, timestamp in messages:
                f.write(f"[{timestamp}] {role}: {content}\n")
        
        print(f"Exported {len(messages)} messages to {filename}")

    conn.close()
    print("Migration complete.")

if __name__ == "__main__":
    migrate()
