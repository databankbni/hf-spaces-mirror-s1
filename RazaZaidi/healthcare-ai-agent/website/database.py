import sqlite3
import os
from datetime import datetime
from contextlib import contextmanager

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.getenv("DB_PATH", os.path.join(PROJECT_ROOT, "healthcare.db"))

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def init_db():
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        c.execute("""CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            response TEXT NOT NULL,
            intent TEXT DEFAULT 'general',
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id))""")
        c.execute("""CREATE TABLE IF NOT EXISTS medical_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_type TEXT NOT NULL,
            file_size INTEGER DEFAULT 0,
            extracted_text TEXT,
            vitals_json TEXT,
            analysis_summary TEXT,
            pages INTEGER DEFAULT 0,
            uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id))""")
        c.execute("""CREATE TABLE IF NOT EXISTS user_health_profile (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            conditions TEXT,  -- JSON array of chronic conditions
            medications TEXT,  -- JSON array of medications
            allergies TEXT,  -- JSON array of allergies
            blood_type TEXT,
            date_of_birth TEXT,
            gender TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id))""")
    print("Database initialized!")

def create_user(username: str, email: str, password: str) -> bool:
    try:
        with get_db() as conn:
            conn.execute("INSERT INTO users (username,email,password) VALUES (?,?,?)",
                        (username, email, password))
        return True
    except Exception:
        return False

def get_user(username: str) -> dict:
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT id,username,email,password FROM users WHERE username=?", (username,))
        row = c.fetchone()
    if row:
        return {"id":row[0],"username":row[1],"email":row[2],"password":row[3]}
    return None

def save_chat(user_id: int, message: str, response: str, intent: str = "general"):
    with get_db() as conn:
        conn.execute("""INSERT INTO chat_history (user_id,message,response,intent,timestamp)
            VALUES (?,?,?,?,?)""", (user_id, message, response, intent, datetime.now().isoformat()))

def get_chat_history(user_id: int, limit: int = 20) -> list:
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""SELECT message,response,intent,timestamp FROM chat_history
            WHERE user_id=? ORDER BY timestamp DESC LIMIT ?""", (user_id, limit))
        rows = c.fetchall()
    return [{"message":r[0],"response":r[1],"intent":r[2],"timestamp":r[3]} for r in reversed(rows)]

def clear_history(user_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM chat_history WHERE user_id=?", (user_id,))

# Medical Reports Functions
def save_medical_report(user_id: int, filename: str, file_path: str, file_type: str, 
                       file_size: int, extracted_text: str, vitals_json: str, 
                       analysis_summary: str, pages: int) -> int:
    """Save uploaded medical report to database. Returns report ID."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""INSERT INTO medical_reports 
            (user_id, filename, file_path, file_type, file_size, extracted_text, 
             vitals_json, analysis_summary, pages, uploaded_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (user_id, filename, file_path, file_type, file_size, extracted_text,
             vitals_json, analysis_summary, pages, datetime.now().isoformat()))
        return cursor.lastrowid

def get_user_reports(user_id: int, limit: int = 20) -> list:
    """Get user's uploaded medical reports"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""SELECT id, filename, file_type, file_size, pages, 
                            analysis_summary, uploaded_at 
                     FROM medical_reports 
                     WHERE user_id=? ORDER BY uploaded_at DESC LIMIT ?""", 
                  (user_id, limit))
        rows = c.fetchall()
    return [{"id": r[0], "filename": r[1], "file_type": r[2], "file_size": r[3],
             "pages": r[4], "analysis": r[5], "uploaded_at": r[6]} for r in rows]

def get_report_by_id(report_id: int, user_id: int) -> dict:
    """Get specific report details (ensures user owns the report)"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""SELECT id, filename, file_path, file_type, file_size, 
                            extracted_text, vitals_json, analysis_summary, 
                            pages, uploaded_at 
                     FROM medical_reports 
                     WHERE id=? AND user_id=?""", (report_id, user_id))
        row = c.fetchone()
    if row:
        return {"id": row[0], "filename": row[1], "file_path": row[2], 
                "file_type": row[3], "file_size": row[4], "extracted_text": row[5],
                "vitals_json": row[6], "analysis_summary": row[7], 
                "pages": row[8], "uploaded_at": row[9]}
    return None

def delete_report(report_id: int, user_id: int) -> bool:
    """Delete a medical report"""
    with get_db() as conn:
        conn.execute("DELETE FROM medical_reports WHERE id=? AND user_id=?", 
                    (report_id, user_id))
        return conn.total_changes > 0

# User Health Profile Functions
def save_health_profile(user_id: int, conditions: str = None, medications: str = None,
                       allergies: str = None, blood_type: str = None, 
                       dob: str = None, gender: str = None):
    """Save or update user's health profile (JSON strings for arrays)"""
    with get_db() as conn:
        conn.execute("""INSERT OR REPLACE INTO user_health_profile 
            (user_id, conditions, medications, allergies, blood_type, date_of_birth, 
             gender, updated_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            (user_id, conditions, medications, allergies, blood_type, dob, 
             gender, datetime.now().isoformat()))

def get_health_profile(user_id: int) -> dict:
    """Get user's health profile"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""SELECT conditions, medications, allergies, blood_type, 
                            date_of_birth, gender FROM user_health_profile 
                     WHERE user_id=?""", (user_id,))
        row = c.fetchone()
    if row:
        return {"conditions": row[0], "medications": row[1], "allergies": row[2],
                "blood_type": row[3], "dob": row[4], "gender": row[5]}
    return None

init_db()
