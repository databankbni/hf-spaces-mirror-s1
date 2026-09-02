import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'mahabharata_chat.db')

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Create Sessions table
    c.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            character_name TEXT NOT NULL,
            last_msg_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, character_name)
        )
    ''')
    
    # Create Messages table
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            role TEXT NOT NULL, -- 'user' or 'assistant'
            content TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(session_id) REFERENCES sessions(id)
        )
    ''')
    
    conn.commit()
    conn.close()

def get_session_id(user_id, character_name):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('SELECT id FROM sessions WHERE user_id = ? AND character_name = ?', (user_id, character_name))
    result = c.fetchone()
    
    if result:
        session_id = result[0]
    else:
        c.execute('INSERT INTO sessions (user_id, character_name) VALUES (?, ?)', (user_id, character_name))
        session_id = c.lastrowid
        conn.commit()
    
    conn.close()
    return session_id

def save_message(user_id, character_name, role, content):
    session_id = get_session_id(user_id, character_name)
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)', (session_id, role, content))
    
    # Update last timestamp
    c.execute('UPDATE sessions SET last_msg_timestamp = CURRENT_TIMESTAMP WHERE id = ?', (session_id,))
    
    conn.commit()
    conn.close()

    # Save to file as well
    try:
        history_dir = os.path.join(os.path.dirname(__file__), '..', 'chat_history')
        if not os.path.exists(history_dir):
            os.makedirs(history_dir)
            
        filename = f"{character_name}_{user_id}.txt"
        filepath = os.path.join(history_dir, filename)
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        with open(filepath, 'a', encoding='utf-8') as f:
            f.write(f"[{timestamp}] {role}: {content}\n")
    except Exception as e:
        print(f"Error saving to file: {e}")

def get_chat_history(user_id, character_name, limit=10):
    history_dir = os.path.join(os.path.dirname(__file__), '..', 'chat_history')
    filename = f"{character_name}_{user_id}.txt"
    filepath = os.path.join(history_dir, filename)
    
    if not os.path.exists(filepath):
        return []
        
    history = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
            # Read last 'limit' lines
            # Format: [timestamp] role: content
            for line in lines[-limit:]:
                # specific parsing logic
                try:
                    # simplistic parsing: assume standard format we write
                    # [2025-...] role: content
                    parts = line.split('] ', 1)
                    if len(parts) < 2: continue
                    
                    meta = parts[0] # [timestamp
                    rest = parts[1]
                    
                    role_content = rest.split(': ', 1)
                    if len(role_content) < 2: continue
                    
                    role = role_content[0].strip().lower() # user or assistant/draupadi etc
                    content = role_content[1].strip()
                    
                    # Normalize role name if needed, but 'user' and 'assistant' are standard keys
                    # In file we write 'user' and 'assistant' from save_message
                    
                    history.append({"role": role, "content": content})
                except:
                    continue
                    
    except Exception as e:
        print(f"Error reading history file: {e}")
        return []

    return history

def clear_chat_history(user_id, character_name):
    """
    Clears all chat history for a specific user and character
    from both the SQLite database and the text file.
    """
    # 1. Clear text file
    history_dir = os.path.join(os.path.dirname(__file__), '..', 'chat_history')
    filename = f"{character_name}_{user_id}.txt"
    filepath = os.path.join(history_dir, filename)
    
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
            print(f"Deleted history file: {filepath}")
        except Exception as e:
            print(f"Error deleting file {filepath}: {e}")
            
    # 2. Clear Database entries
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Get session ID
        c.execute('SELECT id FROM sessions WHERE user_id = ? AND character_name = ?', (user_id, character_name))
        result = c.fetchone()
        
        if result:
            session_id = result[0]
            # Delete messages first (foreign key)
            c.execute('DELETE FROM messages WHERE session_id = ?', (session_id,))
            # Delete session (optional, but cleaner)
            c.execute('DELETE FROM sessions WHERE id = ?', (session_id,))
            conn.commit()
            print(f"Deleted DB records for session {session_id}")
            
        conn.close()
        return True
    except Exception as e:
        print(f"Error clearing DB history: {e}")
        return False

if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
