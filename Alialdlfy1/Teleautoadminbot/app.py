import os
import sys
import time
import subprocess
import threading
import streamlit as st

st.set_page_config(page_title="Telegram Auto Poster")
st.title("🤖 بوت النشر التلقائي")

PID_FILE = "/tmp/telegram_auto_poster_bot.pid"
CORE_LOCK_FILE = "/tmp/telegram_bot_core_running.lock"
LOG_FILE = "/tmp/telegram_auto_poster_bot.log"


def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


def _pid_cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return f.read().replace(b"\x00", b" ").decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _clear_runtime_markers():
    for path in (PID_FILE, CORE_LOCK_FILE):
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


def get_running_pid():
    if not os.path.exists(PID_FILE):
        return None
    try:
        raw = open(PID_FILE, "r", encoding="utf-8").read().strip()
        if not raw:
            _clear_runtime_markers()
            return None
        pid = int(raw)
        if not _pid_is_running(pid):
            _clear_runtime_markers()
            return None

        cmdline = _pid_cmdline(pid)
        if "bot_core" in cmdline and "run_bot" in cmdline:
            return pid

        print(f"[app] stale pid marker ignored: pid={pid} cmdline={cmdline}", flush=True)
        _clear_runtime_markers()
        return None
    except Exception as e:
        print(f"[app] failed reading pid marker, clearing it: {e}", flush=True)
        _clear_runtime_markers()
        return None


def _pipe_logs(process: subprocess.Popen):
    try:
        ROTATION_SECONDS = 24 * 3600  # 48 ساعة
        last_rotation = time.time()
        lf = open(LOG_FILE, "a", encoding="utf-8")
        try:
            for raw in iter(process.stdout.readline, ""):
                if not raw:
                    break
                line = raw.rstrip("\n")
                print(line, flush=True)
                lf.write(line + "\n")
                lf.flush()
                # تدوير السجل تلقائياً كل 48 ساعة
                now = time.time()
                if now - last_rotation >= ROTATION_SECONDS:
                    lf.close()
                    lf = open(LOG_FILE, "w", encoding="utf-8")
                    lf.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] تم مسح السجل تلقائياً (24h rotation)\n")
                    lf.flush()
                    last_rotation = now
                    print("[app] تم مسح ملف السجل تلقائياً (24h rotation)", flush=True)
        finally:
            lf.close()
    except Exception as e:
        print(f"[app] log pipe failed: {e}", flush=True)



def preflight_storage_check():
    """يفحص قاعدة البيانات قبل تشغيل البوت ويستعيد Backup إذا أمكن."""
    try:
        import database as db
        if hasattr(db, "verify_or_recover_storage"):
            return db.verify_or_recover_storage()
        return {"ok": True, "message": "لا يوجد فحص تخزين في database.py"}
    except Exception as e:
        return {"ok": False, "message": f"فشل فحص التخزين: {e}"}

def start_bot_process():
    print("[app] start_bot_process entered", flush=True)
    os.makedirs("/data", exist_ok=True)

    storage_status = preflight_storage_check()
    print(f"[app] storage preflight: {storage_status.get('message')}", flush=True)
    if not storage_status.get("ok"):
        return None, False, "storage:" + str(storage_status.get("message"))

    existing_pid = get_running_pid()
    if existing_pid:
        return existing_pid, False, None

    try:
        if os.path.exists(CORE_LOCK_FILE):
            os.remove(CORE_LOCK_FILE)
    except Exception:
        pass

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    cmd = [sys.executable, "-u", "-c", "from bot_core import run_bot; run_bot()"]
    print(f"[app] starting bot process: {' '.join(cmd)}", flush=True)

    process = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )

    threading.Thread(target=_pipe_logs, args=(process,), daemon=True).start()

    with open(PID_FILE, "w", encoding="utf-8") as f:
        f.write(str(process.pid))

    time.sleep(2)
    exit_code = process.poll()
    if exit_code is not None:
        try:
            os.remove(PID_FILE)
        except Exception:
            pass
        return process.pid, True, exit_code

    return process.pid, True, None


pid, started_now, exit_code = start_bot_process()

if exit_code is not None:
    if isinstance(exit_code, str) and exit_code.startswith("storage:"):
        st.error("❌ تم إيقاف التشغيل لحماية بياناتك.")
        st.warning(exit_code.replace("storage:", "", 1))
    else:
        st.error(f"❌ فشل تشغيل البوت. PID: {pid} | Exit code: {exit_code}")
        st.warning("افتح Logs وشوف الخطأ الذي يبدأ بـ Traceback أو ERROR.")
elif started_now:
    st.success(f"✅ تم تشغيل البوت بنجاح. PID: {pid}")
else:
    st.success(f"✅ البوت يعمل مسبقاً. PID: {pid}")

st.info("البوت يعمل في الخلفية. استخدم تيليجرام للتحكم.")

with st.expander("معلومات التشغيل"):
    st.write("إذا غيّرت Secrets أو رفعت ملفات جديدة، استخدم Restart Space من Hugging Face.")
    st.write("PID file:", PID_FILE)
    st.write("Core lock file:", CORE_LOCK_FILE)
    st.write("Bot log file:", LOG_FILE)
    st.write("تم إخفاء سجل البوت من صفحة App حتى تبقى الصفحة خفيفة. راجع تبويب Logs عند الحاجة.")
