"""Server-side conversation storage in MySQL for cross-browser chat history."""

import json
import uuid
from datetime import datetime
from mysql.connector import Error
from config import Config
from database.connector import DatabaseConnector


class ChatStore:
    """Manages conversation persistence in MySQL."""

    def __init__(self, db: DatabaseConnector):
        self.db = db
        self._ensure_tables()

    def _ensure_tables(self):
        """Create conversations and messages tables if they don't exist."""
        connection = None
        try:
            connection = self.db.get_connection()
            cursor = connection.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id VARCHAR(36) PRIMARY KEY,
                    title VARCHAR(255) NOT NULL,
                    pinned TINYINT(1) DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)

            # Migration: add pinned column if it doesn't exist yet
            try:
                cursor.execute("ALTER TABLE conversations ADD COLUMN pinned TINYINT(1) DEFAULT 0")
                connection.commit()
            except Error:
                pass  # Column already exists

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    conversation_id VARCHAR(36) NOT NULL,
                    role VARCHAR(20) NOT NULL,
                    content TEXT,
                    data JSON,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
                    INDEX idx_conv_id (conversation_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)

            connection.commit()
            print("[ChatStore] Tables ready.")

        except Error as e:
            print(f"[ChatStore] Table creation failed: {e}")
        finally:
            if connection:
                connection.close()

    def create_conversation(self, title: str) -> str:
        """Create a new conversation, return its ID."""
        conv_id = str(uuid.uuid4())[:8]
        connection = None
        try:
            connection = self.db.get_connection()
            cursor = connection.cursor()
            cursor.execute(
                "INSERT INTO conversations (id, title) VALUES (%s, %s)",
                (conv_id, title[:255])
            )
            connection.commit()
            return conv_id
        except Error as e:
            print(f"[ChatStore] Create failed: {e}")
            return ""
        finally:
            if connection:
                connection.close()

    def get_conversations(self) -> list:
        """Get all conversations, pinned first then newest first."""
        connection = None
        try:
            connection = self.db.get_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute("""
                SELECT id, title, pinned, created_at, updated_at
                FROM conversations
                ORDER BY pinned DESC, updated_at DESC
            """)
            rows = cursor.fetchall()
            for row in rows:
                row["pinned"] = bool(row.get("pinned", 0))
                if row.get("created_at") and hasattr(row["created_at"], "isoformat"):
                    row["created_at"] = row["created_at"].isoformat()
                if row.get("updated_at") and hasattr(row["updated_at"], "isoformat"):
                    row["updated_at"] = row["updated_at"].isoformat()
            return rows
        except Error as e:
            print(f"[ChatStore] List failed: {e}")
            return []
        finally:
            if connection:
                connection.close()

    def get_messages(self, conversation_id: str) -> list:
        """Get all messages for a conversation."""
        connection = None
        try:
            connection = self.db.get_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                "SELECT role, content, data FROM messages WHERE conversation_id = %s ORDER BY id",
                (conversation_id,)
            )
            rows = cursor.fetchall()
            for row in rows:
                if row.get("data") and isinstance(row["data"], str):
                    try:
                        row["data"] = json.loads(row["data"])
                    except (json.JSONDecodeError, TypeError):
                        pass
            return rows
        except Error as e:
            print(f"[ChatStore] Get messages failed: {e}")
            return []
        finally:
            if connection:
                connection.close()

    def add_message(self, conversation_id: str, role: str, content: str, data: dict = None):
        """Add a message to a conversation."""
        connection = None
        try:
            connection = self.db.get_connection()
            cursor = connection.cursor()
            data_json = json.dumps(data, default=str) if data else None
            cursor.execute(
                "INSERT INTO messages (conversation_id, role, content, data) VALUES (%s, %s, %s, %s)",
                (conversation_id, role, content, data_json)
            )
            # Touch updated_at on the conversation
            cursor.execute(
                "UPDATE conversations SET updated_at = NOW() WHERE id = %s",
                (conversation_id,)
            )
            connection.commit()
        except Error as e:
            print(f"[ChatStore] Add message failed: {e}")
        finally:
            if connection:
                connection.close()

    def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation and its messages."""
        connection = None
        try:
            connection = self.db.get_connection()
            cursor = connection.cursor()
            cursor.execute("DELETE FROM conversations WHERE id = %s", (conversation_id,))
            connection.commit()
            return cursor.rowcount > 0
        except Error as e:
            print(f"[ChatStore] Delete failed: {e}")
            return False
        finally:
            if connection:
                connection.close()

    def clear_all(self) -> int:
        """Delete all conversations. Returns count deleted."""
        connection = None
        try:
            connection = self.db.get_connection()
            cursor = connection.cursor()
            cursor.execute("SELECT COUNT(*) FROM conversations")
            count = cursor.fetchone()[0]
            cursor.execute("DELETE FROM conversations")
            connection.commit()
            return count
        except Error as e:
            print(f"[ChatStore] Clear failed: {e}")
            return 0
        finally:
            if connection:
                connection.close()

    def get_recent_history(self, conversation_id: str, limit: int = 10) -> list:
        """Get recent messages for multi-turn context."""
        connection = None
        try:
            connection = self.db.get_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """SELECT role, content FROM messages
                   WHERE conversation_id = %s AND role IN ('user', 'assistant')
                   ORDER BY id DESC LIMIT %s""",
                (conversation_id, limit)
            )
            rows = cursor.fetchall()
            rows.reverse()  # Oldest first
            return rows
        except Error as e:
            return []
        finally:
            if connection:
                connection.close()

    def rename_conversation(self, conversation_id: str, new_title: str) -> bool:
        """Rename a conversation."""
        connection = None
        try:
            connection = self.db.get_connection()
            cursor = connection.cursor()
            cursor.execute(
                "UPDATE conversations SET title = %s WHERE id = %s",
                (new_title[:255], conversation_id)
            )
            connection.commit()
            return cursor.rowcount > 0
        except Error as e:
            print(f"[ChatStore] Rename failed: {e}")
            return False
        finally:
            if connection:
                connection.close()

    def pin_conversation(self, conversation_id: str, pinned: bool) -> bool:
        """Pin or unpin a conversation."""
        connection = None
        try:
            connection = self.db.get_connection()
            cursor = connection.cursor()
            cursor.execute(
                "UPDATE conversations SET pinned = %s, updated_at = updated_at WHERE id = %s",
                (1 if pinned else 0, conversation_id)
            )
            connection.commit()
            return cursor.rowcount > 0
        except Error as e:
            print(f"[ChatStore] Pin failed: {e}")
            return False
        finally:
            if connection:
                connection.close()
