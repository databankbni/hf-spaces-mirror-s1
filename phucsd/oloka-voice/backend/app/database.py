import os
import glob
import shutil
import sqlite3
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.event import listens_for
from app.config import settings

def test_db_writable(db_url: str) -> bool:
    if not db_url.startswith("sqlite"):
        return True
    
    # Extract file path
    db_path = db_url
    if db_path.startswith("sqlite:///"):
        db_path = db_path[10:]
    elif db_path.startswith("sqlite://"):
        db_path = db_path[9:]
    elif db_path.startswith("sqlite:"):
        db_path = db_path[7:]
    if "?" in db_path:
        db_path = db_path.split("?")[0]
        
    parent_dir = os.path.dirname(db_path)
    if parent_dir:
        try:
            os.makedirs(parent_dir, exist_ok=True)
        except Exception as e:
            print(f"[Database Init] Failed to create directory {parent_dir}: {e}")
            return False
            
    import sqlite3
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=DELETE")
        cursor.execute("CREATE TABLE IF NOT EXISTS _write_test (id INTEGER PRIMARY KEY)")
        cursor.execute("INSERT INTO _write_test DEFAULT VALUES")
        cursor.execute("DROP TABLE _write_test")
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[Database Init] Write verification failed for {db_path}: {e}")
        if conn:
            try:
                conn.close()
            except:
                pass
        return False

def check_and_recover_database(db_url: str):
    if not db_url.startswith("sqlite"):
        return
        
    db_path = db_url
    if db_path.startswith("sqlite:///"):
        db_path = db_path[10:]
    elif db_path.startswith("sqlite://"):
        db_path = db_path[9:]
    elif db_path.startswith("sqlite:"):
        db_path = db_path[7:]
    if "?" in db_path:
        db_path = db_path.split("?")[0]
        
    if not os.path.exists(db_path):
        return
        
    import sqlite3
    import time
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check")
        result = cursor.fetchone()[0]
        conn.close()
        if result == "ok":
            print(f"[Database Integrity] Check passed for {db_path}")
            return
        print(f"[Database Integrity] CORRUPTED database found at {db_path}: integrity_check={result}")
    except Exception as e:
        print(f"[Database Integrity] Error verifying database {db_path}: {e}")
        if conn:
            try:
                conn.close()
            except:
                pass

    # Reaching here means database is corrupt. Rename and recover.
    backup_path = f"{db_path}.corrupt_{int(time.time())}"
    print(f"[Database Integrity] Renaming corrupted database to {backup_path}")
    try:
        if os.path.exists(db_path):
            os.rename(db_path, backup_path)
        # Also clean up stale lock files
        for suffix in ["-shm", "-wal"]:
            lock_file = db_path + suffix
            if os.path.exists(lock_file):
                os.remove(lock_file)
        print("[Database Integrity] Corrupted database recovered by recreating file.")
    except Exception as ex:
        print(f"[Database Integrity Error] Failed to rename corrupted database: {ex}")

# Check and recover database if corrupted
check_and_recover_database(settings.DATABASE_URL)

# Resolve Database URL with dynamic writeability fallback checks
resolved_db_url = settings.DATABASE_URL
if resolved_db_url.startswith("sqlite"):
    if not test_db_writable(resolved_db_url):
        print(f"[Database Init] Warning: Default database path {resolved_db_url} is not writable.")
        
        # Fallback 1: Try ./storage/ directory
        fallback_storage = "sqlite:///./storage/omnivoice_gateway.db"
        print(f"[Database Init] Attempting fallback 1: {fallback_storage}")
        if test_db_writable(fallback_storage):
            resolved_db_url = fallback_storage
            print(f"[Database Init] Success: Using fallback 1 ({fallback_storage})")
        else:
            # Fallback 2: Try /tmp/
            fallback_2 = "sqlite:////tmp/omnivoice_gateway.db"
            print(f"[Database Init] Attempting fallback 2: {fallback_2}")
            if test_db_writable(fallback_2):
                resolved_db_url = fallback_2
                print(f"[Database Init] Success: Using fallback 2")
            else:
                fallback_3 = "sqlite:///./omnivoice_gateway_fallback.db"
                resolved_db_url = fallback_3
                print(f"[Database Init] Using fallback 3")
        
        # Override the setting globally so all routes and services use the working database path
        settings.DATABASE_URL = resolved_db_url

# Cleanup stale SQLite WAL/SHM lock files on start to prevent disk I/O errors on network drives
if settings.DATABASE_URL.startswith("sqlite"):
    db_path = settings.DATABASE_URL
    if db_path.startswith("sqlite:///"):
        db_path = db_path[10:]
    elif db_path.startswith("sqlite://"):
        db_path = db_path[9:]
    elif db_path.startswith("sqlite:"):
        db_path = db_path[7:]
    if "?" in db_path:
        db_path = db_path.split("?")[0]
        
    for suffix in ["-shm", "-wal"]:
        lock_file = db_path + suffix
        if os.path.exists(lock_file):
            try:
                os.remove(lock_file)
                print(f"[Database] Removed stale lock file: {lock_file}")
            except Exception as e:
                print(f"[Database Error] Failed to remove lock file {lock_file}: {e}")

# For SQLite, we need connect_args={"check_same_thread": False, "timeout": 30, "uri": True}
connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args = {
        "check_same_thread": False,
        "timeout": 30,
        "uri": True
    }

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    echo=False
)


# Apply performance and lock-avoidance pragmas to SQLite connections
@listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if settings.DATABASE_URL.startswith("sqlite"):
        try:
            cursor = dbapi_connection.cursor()
            # Force DELETE journal mode to avoid .shm / .wal lock files on NFS
            cursor.execute("PRAGMA journal_mode=DELETE")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()
        except Exception as e:
            print(f"[Database Pragma] Failed to set SQLite pragmas: {e}")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def migrate_database(db_url: str):
    if not db_url.startswith("sqlite"):
        return
    
    import os
    # Clean up prefix and query params to get raw file path
    db_path = db_url
    if db_path.startswith("sqlite:///"):
        db_path = db_path[10:]
    elif db_path.startswith("sqlite://"):
        db_path = db_path[9:]
    elif db_path.startswith("sqlite:"):
        db_path = db_path[7:]
        
    if "?" in db_path:
        db_path = db_path.split("?")[0]
        
    if not os.path.exists(db_path):
        return
    
    import sqlite3
    print(f"[Migration] Checking database file: {db_path}")
    conn = sqlite3.connect(db_path, timeout=30)
    cursor = conn.cursor()
    
    try:
        # Check if tts_jobs table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tts_jobs'")
        if not cursor.fetchone():
            conn.close()
            return
            
        cursor.execute("PRAGMA table_info(tts_jobs)")
        columns = [row[1] for row in cursor.fetchall()]
        
        new_cols = {
            "denoise": "BOOLEAN DEFAULT 1",
            "guidance_scale": "FLOAT DEFAULT 2.0",
            "t_shift": "FLOAT DEFAULT 0.1",
            "position_temperature": "FLOAT DEFAULT 5.0",
            "class_temperature": "FLOAT DEFAULT 0.0",
            "layer_penalty_factor": "FLOAT DEFAULT 5.0",
            "duration": "FLOAT",
            "preprocess_prompt": "BOOLEAN DEFAULT 1",
            "postprocess_output": "BOOLEAN DEFAULT 1",
            "audio_chunk_duration": "FLOAT DEFAULT 15.0",
            "audio_chunk_threshold": "FLOAT DEFAULT 30.0",
            "batch_id": "VARCHAR(50)",
            "compat_id": "VARCHAR(100)",
            "with_alignment": "BOOLEAN DEFAULT 0",
            "alignment": "TEXT",
            "started_at": "DATETIME",
            "completed_at": "DATETIME",
            "language": "VARCHAR(50)",
            "pad_duration": "FLOAT",
            "fade_duration": "FLOAT",
            "cdn_audio_url": "TEXT"
        }
        
        for col, col_type in new_cols.items():
            if col not in columns:
                cursor.execute(f"ALTER TABLE tts_jobs ADD COLUMN {col} {col_type}")
                print(f"[Migration] Added column {col} to tts_jobs table in {db_path}")
        
        # Check and migrate voice_samples table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='voice_samples'")
        if cursor.fetchone():
            cursor.execute("PRAGMA table_info(voice_samples)")
            vs_columns = [row[1] for row in cursor.fetchall()]
            
            vs_new_cols = {
                "name": "VARCHAR(100)",
                "is_public": "BOOLEAN DEFAULT 0",
                "source_job_id": "VARCHAR(50)",
                "tags": "TEXT",
                "source_job_data": "TEXT"
            }
            for col, col_type in vs_new_cols.items():
                if col not in vs_columns:
                    cursor.execute(f"ALTER TABLE voice_samples ADD COLUMN {col} {col_type}")
                    print(f"[Migration] Added column {col} to voice_samples table in {db_path}")
                    
        # Check and migrate video_dubbing_jobs table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='video_dubbing_jobs'")
        if cursor.fetchone():
            cursor.execute("PRAGMA table_info(video_dubbing_jobs)")
            vd_columns = [row[1] for row in cursor.fetchall()]
            
            vd_new_cols = {
                "llm_profile_id": "VARCHAR(50)",
                "vocals_volume": "FLOAT DEFAULT 1.0",
                "bgm_volume": "FLOAT DEFAULT 0.4"
            }
            for col, col_type in vd_new_cols.items():
                if col not in vd_columns:
                    cursor.execute(f"ALTER TABLE video_dubbing_jobs ADD COLUMN {col} {col_type}")
                    print(f"[Migration] Added column {col} to video_dubbing_jobs table in {db_path}")

        conn.commit()
    except Exception as e:
        print(f"[Migration Error] Failed to migrate database {db_path}: {e}")
    finally:
        conn.close()

    # Automatically rescue data from any backed up corrupted database files
    salvage_corrupted_databases(db_url)
    auto_align_legacy_user_ids(db_url)

def auto_align_legacy_user_ids(db_url: str):
    if not db_url.startswith("sqlite"):
        return
        
    db_path = db_url
    if db_path.startswith("sqlite:///"):
        db_path = db_path[10:]
    elif db_path.startswith("sqlite://"):
        db_path = db_path[9:]
    elif db_path.startswith("sqlite:"):
        db_path = db_path[7:]
    if "?" in db_path:
        db_path = db_path.split("?")[0]
        
    if not os.path.exists(db_path):
        return
        
    import sqlite3
    conn = sqlite3.connect(db_path, timeout=30)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM users WHERE email = 'phucsd@gmail.com' OR username = 'phucsd@gmail.com' OR username = 'admin' OR is_admin = 1 ORDER BY is_admin DESC")
        row = cursor.fetchone()
        if row:
            admin_id = row[0]
            cursor.execute("UPDATE voice_samples SET user_id = ? WHERE user_id != ?", (admin_id, admin_id))
            cursor.execute("UPDATE api_keys SET user_id = ? WHERE user_id != ?", (admin_id, admin_id))
            cursor.execute("UPDATE tts_jobs SET user_id = ? WHERE user_id != ?", (admin_id, admin_id))
            cursor.execute("UPDATE user_settings SET user_id = ? WHERE user_id != ?", (admin_id, admin_id))
            conn.commit()
            print(f"[Database Auto-Align] Permanently aligned legacy user_id to admin ID: {admin_id}")
    except Exception as e:
        print(f"[Database Auto-Align Error] {e}")
    finally:
        conn.close()

def salvage_corrupted_databases(db_url: str):
    if not db_url.startswith("sqlite"):
        return
        
    db_path = db_url
    if db_path.startswith("sqlite:///"):
        db_path = db_path[10:]
    elif db_path.startswith("sqlite://"):
        db_path = db_path[9:]
    elif db_path.startswith("sqlite:"):
        db_path = db_path[7:]
    if "?" in db_path:
        db_path = db_path.split("?")[0]
        
    db_dir = os.path.dirname(db_path) or "."
    base_name = os.path.basename(db_path)
    
    if not os.path.exists(db_dir):
        return
        
    # Clean up any leftover recursive .restored or lock backup files
    for f in glob.glob(os.path.join(db_dir, f"{base_name}.corrupt_*")):
        if f.count(".restored") > 0 or f.endswith("-shm") or f.endswith("-wal") or "-shm." in f or "-wal." in f:
            try: os.remove(f)
            except: pass
            
    corrupt_files = [
        f for f in glob.glob(os.path.join(db_dir, f"{base_name}.corrupt_*"))
        if not f.endswith("-shm") and not f.endswith("-wal") and not f.endswith(".restored") and ".restored" not in f and "-shm." not in f and "-wal." not in f
    ]
    
    if not corrupt_files:
        return
        
    print(f"[Database Salvage] Found {len(corrupt_files)} corrupted backup database file(s) to restore.")
    
    tables_to_restore = [
        "users", "api_keys", "voice_samples", "llm_profiles",
        "system_settings", "tts_jobs", "worker_sessions", "api_usage_logs"
    ]
    
    try:
        target_conn = sqlite3.connect(db_path, timeout=30)
        target_cursor = target_conn.cursor()
    except Exception as e:
        print(f"[Database Salvage Error] Failed to connect to active database {db_path}: {e}")
        return
    
    for corrupt_file in corrupt_files:
        print(f"[Database Salvage] Rescuing data from {corrupt_file}...")
        try:
            source_conn = sqlite3.connect(f"file:{corrupt_file}?mode=ro", uri=True, timeout=10)
            source_cursor = source_conn.cursor()
            
            for table in tables_to_restore:
                try:
                    source_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
                    if not source_cursor.fetchone():
                        continue
                        
                    target_cursor.execute(f"PRAGMA table_info({table})")
                    target_cols = [row[1] for row in target_cursor.fetchall()]
                    if not target_cols:
                        continue
                        
                    source_cursor.execute(f"PRAGMA table_info({table})")
                    source_cols = [row[1] for row in source_cursor.fetchall()]
                    
                    common_cols = [c for c in source_cols if c in target_cols]
                    if not common_cols:
                        continue
                        
                    col_names = ", ".join(common_cols)
                    placeholders = ", ".join(["?"] * len(common_cols))
                    
                    rows = []
                    try:
                        source_cursor.execute(f"SELECT {col_names} FROM {table}")
                        rows = source_cursor.fetchall()
                    except Exception as select_err:
                        print(f"[Database Salvage] Table fetch error for '{table}': {select_err}. Attempting rowid fallback...")
                        try:
                            source_cursor.execute(f"SELECT rowid FROM {table}")
                            rowids = [r[0] for r in source_cursor.fetchall()]
                            for rid in rowids:
                                try:
                                    source_cursor.execute(f"SELECT {col_names} FROM {table} WHERE rowid=?", (rid,))
                                    r_item = source_cursor.fetchone()
                                    if r_item:
                                        rows.append(r_item)
                                except Exception:
                                    pass
                        except Exception:
                            pass
                    
                    if rows:
                        insert_sql = f"INSERT OR REPLACE INTO {table} ({col_names}) VALUES ({placeholders})"
                        restored_count = 0
                        for row in rows:
                            try:
                                target_cursor.execute(insert_sql, row)
                                restored_count += 1
                            except Exception:
                                pass
                        target_conn.commit()
                        print(f"[Database Salvage] Restored {restored_count}/{len(rows)} records into '{table}'")
                except Exception as table_err:
                    print(f"[Database Salvage Error] Table '{table}': {table_err}")
            
            source_conn.close()
            restored_path = f"{corrupt_file}.restored"
            os.rename(corrupt_file, restored_path)
            print(f"[Database Salvage] Data recovery completed for {corrupt_file} -> {restored_path}")
        except Exception as file_err:
            print(f"[Database Salvage Error] Opening {corrupt_file}: {file_err}")
            
    target_conn.close()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Execute migration automatically on import
try:
    migrate_database(settings.DATABASE_URL)
except Exception as _mig_err:
    print(f"[Database Migration Warning] {_mig_err}")
