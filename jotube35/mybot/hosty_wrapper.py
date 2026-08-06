import subprocess, os, threading, logging, time, requests, base64, hashlib
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

from flask import Flask
from flask_cors import CORS

HOSTY_API = "https://hostapp-hosty.hf.space"
BOT_NAME = "mybot"
SYNC_KEY = os.environ.get("SYNC_KEY")

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
app = Flask(__name__)
CORS(app)

LAST_HASHES = {}

def get_file_hash(filepath):
    hasher = hashlib.md5()
    try:
        with open(filepath, 'rb') as afile:
            buf = afile.read()
            hasher.update(buf)
        return hasher.hexdigest()
    except:
        return None

def get_disk_usage():
    total_size = 0
    try:
        for dirpath, _, filenames in os.walk('.'):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if not os.path.islink(fp):
                    total_size += os.path.getsize(fp)
    except: pass
    return round(total_size / (1024 * 1024), 2)

def get_dynamic_files():
    global LAST_HASHES
    files_to_sync = {}
    current_hashes = {}
    for root, dirs, files in os.walk('.'):
        if 'node_modules' in root or '.git' in root or '__pycache__' in root:
            continue
        for f in files:
            valid_exts = ('.json', '.sqlite', '.db', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.txt', '.csv')
            if f.endswith(valid_exts):
                if f in ['package.json', 'package-lock.json']: continue
                path = os.path.join(root, f)
                try:
                    if os.path.getsize(path) < 15 * 1024 * 1024: 
                        file_hash = get_file_hash(path)
                        current_hashes[path] = file_hash
                        if LAST_HASHES.get(path) != file_hash:
                            with open(path, 'rb') as file_obj:
                                files_to_sync[path] = base64.b64encode(file_obj.read()).decode('utf-8')
                except: pass
    LAST_HASHES = current_hashes
    return files_to_sync

def sync_up():
    time.sleep(5)
    while True:
        try:
            files = get_dynamic_files()
            
            ram = 45.0
            cpu = 1.0
            if HAS_PSUTIL:
                try:
                    p = psutil.Process(os.getpid())
                    r = p.memory_info().rss
                    c = p.cpu_percent(interval=0.1)
                    for child in p.children(recursive=True):
                        try:
                            r += child.memory_info().rss
                            c += child.cpu_percent(interval=0.1)
                        except: pass
                    ram = round(r / (1024 * 1024), 1)
                    cpu = round(c, 1)
                except: pass

            stats = {
                "ram": ram,
                "cpu": cpu,
                "disk": get_disk_usage()
            }
            
            if SYNC_KEY:
                res = requests.post(f"{HOSTY_API}/api/sync-up/{BOT_NAME}", json={"files": files, "stats": stats}, headers={"Authorization": SYNC_KEY}, timeout=20)
                if res.status_code != 200:
                    pass
        except Exception as e:
            pass
        time.sleep(60)

def sync_down(): 
    try:
        if SYNC_KEY:
            res = requests.get(f"{HOSTY_API}/api/sync-down/{BOT_NAME}", headers={"Authorization": SYNC_KEY}, timeout=20)
            if res.status_code == 200:
                files = res.json().get("files", {})
                for path, b64content in files.items():
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, 'wb') as f:
                        f.write(base64.b64decode(b64content))
                global LAST_HASHES
                for path in files.keys(): LAST_HASHES[path] = get_file_hash(path)
    except: pass

@app.route('/')
def home(): return 'Running'

@app.route('/hosty_logs')
def get_logs():
    try:
        with open('bot_log.txt', 'r', encoding='utf-8') as file: return file.read()[-20000:]
    except: return 'Waiting for logs...'

def run_bot():
    sync_down() 
    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    
    # === حقن المصفاة السحرية في بيئة التشغيل ===
    env["PYTHONPATH"] = "/app"
    env["NODE_OPTIONS"] = "--require /app/hosty_global_patch.js"
    # ============================================

    for k in list(env.keys()):
        if k.startswith('SPACE_') or k.startswith('HF_'):
            del env[k]

    with open('bot_log.txt', 'a', encoding='utf-8') as log_file:
        try:
            process = subprocess.Popen(['node', 'hosty_net_patch.js'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, text=True, bufsize=1)
            for line in process.stdout:
                log_file.write(line)
                log_file.flush()
            process.wait()
            log_file.write(f"\n[SYSTEM] ⚠️ البوت توقف عن العمل! (Exit Code: {process.returncode})\n")
        except Exception as e:
            log_file.write(f"\n[SYSTEM] ❌ فشل تشغيل البوت: {str(e)}\n")
        log_file.flush()

if __name__ == '__main__':
    threading.Thread(target=run_bot, daemon=True).start()
    threading.Thread(target=sync_up, daemon=True).start()
    app.run(host='0.0.0.0', port=7860)
