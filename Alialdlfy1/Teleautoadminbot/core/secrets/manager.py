"""Encrypted persistent secret store with additive master-key rotation."""
import base64, json, os, sqlite3, threading
from datetime import datetime, timezone
try:
    from cryptography.fernet import Fernet
except ImportError:  # pragma: no cover
    Fernet = None

class SecretManager:
    def __init__(self, db_path: str, allow_unconfigured: bool = False):
        self.db_path = db_path; self._lock = threading.RLock()
        key = os.getenv("P29_SECRET_MASTER_KEY")
        if not key or Fernet is None:
            if allow_unconfigured: self._fernet = None
            else: raise RuntimeError("SecretManager requires P29_SECRET_MASTER_KEY and cryptography")
        else: self._fernet = Fernet(key.encode() if isinstance(key, str) else key)
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        with sqlite3.connect(db_path) as c:
            c.execute("CREATE TABLE IF NOT EXISTS secrets(name TEXT PRIMARY KEY, kind TEXT NOT NULL, value BLOB NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, meta TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL)")

    def set(self, name, value, kind="generic", meta=None, enabled=True):
        if self._fernet is None: raise RuntimeError("Secret store is not configured: set P29_SECRET_MASTER_KEY")
        blob = self._fernet.encrypt(value.encode()); now = datetime.now(timezone.utc).isoformat()
        with self._lock, sqlite3.connect(self.db_path) as c:
            c.execute("INSERT INTO secrets(name,kind,value,enabled,meta,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET kind=excluded.kind,value=excluded.value,enabled=excluded.enabled,meta=excluded.meta,updated_at=excluded.updated_at", (name,kind,blob,int(enabled),json.dumps(meta or {}),now))

    def get(self, name):
        with sqlite3.connect(self.db_path) as c: row=c.execute("SELECT value,enabled FROM secrets WHERE name=?",(name,)).fetchone()
        if not row or not row[1] or self._fernet is None:return None
        return self._fernet.decrypt(row[0]).decode()

    def list_metadata(self):
        with sqlite3.connect(self.db_path) as c:return c.execute("SELECT name,kind,enabled,meta,updated_at FROM secrets ORDER BY name").fetchall()

    def rotate_master_key(self, new_key: str):
        if self._fernet is None: raise RuntimeError("secret store is not configured")
        new_fernet = Fernet(new_key.encode() if isinstance(new_key,str) else new_key)
        with self._lock, sqlite3.connect(self.db_path) as c:
            rows=c.execute("SELECT name,value FROM secrets").fetchall()
            decrypted=[(name,self._fernet.decrypt(blob)) for name,blob in rows]
            for name,plain in decrypted:
                c.execute("UPDATE secrets SET value=?,updated_at=? WHERE name=?",(new_fernet.encrypt(plain),datetime.now(timezone.utc).isoformat(),name))
        self._fernet = new_fernet
        return len(decrypted)
