"""
Mira Cloud Relay — deploy lên Render
Agent ở nhà push log vào đây → web UI + Claude API
"""
import os, re, json, time, threading, pathlib, hashlib
from datetime import datetime
from flask import Flask, jsonify, request, Response

app = Flask(__name__)

RELAY_KEY = os.environ.get("RELAY_KEY", "mira-relay-key-2026")
MAX_LOGS  = 2000

# ── State ─────────────────────────────────────────────────────
log_entries: list[dict] = []
log_lock  = threading.Lock()
_log_seq  = 0

device_state = {
    "esp32": False, "wifi": False, "mira": False,
    "port": None, "last_user": "", "last_mira": "",
    "upload_running": False, "last_seen": None,
    # Tín hiệu phần cứng parse từ serial log của firmware
    "emotion": "neutral", "face_state": None,
    "mic_amp": None, "oled_addr": None, "oled_ok": None, "speaker_ok": None,
}

# ── Parse tín hiệu phần cứng từ dòng log firmware ─────────────
_RE_FACE    = re.compile(r"\[Face\].*?(IDLE|LISTENING|THINKING|SPEAKING)\s*\(emotion:\s*(\w+)\)")
_RE_MIC     = re.compile(r"\[Mic-test\].*?max=(\d+)")
_RE_I2C     = re.compile(r"\[I2C\].*?0x([0-9A-Fa-f]{2})")

def _parse_device_signals(text: str):
    m = _RE_FACE.search(text)
    if m:
        device_state["face_state"] = m.group(1)
        device_state["emotion"]    = m.group(2)
    m = _RE_MIC.search(text)
    if m:
        device_state["mic_amp"] = int(m.group(1))
    m = _RE_I2C.search(text)
    if m:
        device_state["oled_addr"] = "0x" + m.group(1).upper()
    if "[OLED] ✓" in text:      device_state["oled_ok"] = True
    elif "[OLED] ✗" in text:    device_state["oled_ok"] = False
    if "Beep OK" in text:       device_state["speaker_ok"] = True

_pending_cmd: dict | None = None
_cmd_lock = threading.Lock()

def _store_logs(batch: list[dict]):
    global _log_seq
    with log_lock:
        for entry in batch:
            entry["seq"] = _log_seq
            _log_seq += 1
            log_entries.append(entry)
            _parse_device_signals(entry.get("text", ""))
        while len(log_entries) > MAX_LOGS:
            log_entries.pop(0)

# ── Ingest (agent → relay) ────────────────────────────────────
@app.route("/ingest", methods=["POST"])
def ingest():
    global _pending_cmd
    data = request.json or {}
    if data.get("key") != RELAY_KEY:
        return jsonify({"error": "unauthorized"}), 401

    device_state.update(data.get("state", {}))
    device_state["last_seen"] = datetime.now().strftime("%H:%M:%S")

    _store_logs(data.get("logs", []))

    with _cmd_lock:
        cmd = _pending_cmd
        _pending_cmd = None

    return jsonify({"ok": True, "command": cmd})

# ── Claude / external API ─────────────────────────────────────
@app.route("/api/log/latest")
def api_log_latest():
    n = int(request.args.get("n", 100))
    with log_lock:
        entries = list(log_entries[-n:])
    return jsonify({
        "total": len(log_entries),
        "returned": len(entries),
        "state": device_state,
        "entries": entries,
    })

@app.route("/api/state")
def api_state():
    return jsonify(device_state)

@app.route("/api/log/download")
def api_log_download():
    with log_lock:
        lines = [f"[{e['ts']}] {e['text']}" + (f"  → FIX: {e['fix']}" if e.get('fix') else "")
                 for e in log_entries]
    body = "\n".join(lines) or "(chưa có log)"
    return Response(body, mimetype="text/plain",
                    headers={"Content-Disposition": "attachment; filename=mira-log.txt"})

@app.route("/api/diagnose")
def api_diagnose():
    with log_lock:
        recent = log_entries[-50:]
    seen, issues = set(), []
    for e in recent:
        if e.get("fix") and e["fix"] not in seen:
            seen.add(e["fix"])
            issues.append({"log": e["text"][:80], "fix": e["fix"], "ts": e["ts"]})
    return jsonify({
        "status": "ok" if not issues else "issues_found",
        "issues": issues,
        "device_state": device_state,
    })

# ── Kho firmware ──────────────────────────────────────────────
# Máy dev build .bin rồi đẩy lên đây; agent ở nhà tải về flash bằng esptool.
# → PC nhà KHÔNG cần source code, git hay PlatformIO.
_fw_lock  = threading.Lock()
_firmware = {"data": None, "sha": None, "commit": None, "size": 0, "ts": None}

@app.route("/api/firmware", methods=["POST"])
def api_firmware_upload():
    if request.headers.get("X-Relay-Key") != RELAY_KEY:
        return jsonify({"error": "unauthorized"}), 401
    blob = request.get_data()
    if not blob:
        return jsonify({"error": "empty body"}), 400
    sha = hashlib.sha256(blob).hexdigest()
    with _fw_lock:
        _firmware.update(data=blob, sha=sha, size=len(blob),
                         commit=request.headers.get("X-Commit", "?"),
                         ts=datetime.now().strftime("%H:%M:%S"))
    return jsonify({"ok": True, "sha256": sha, "size": len(blob)})

@app.route("/api/firmware/meta")
def api_firmware_meta():
    with _fw_lock:
        if not _firmware["data"]:
            return jsonify({"available": False}), 404
        return jsonify({"available": True, "sha256": _firmware["sha"],
                        "size": _firmware["size"],
                        "commit": _firmware["commit"], "ts": _firmware["ts"]})

@app.route("/api/firmware/bin")
def api_firmware_bin():
    with _fw_lock:
        blob = _firmware["data"]
    if not blob:
        return jsonify({"error": "chưa có firmware — máy dev chạy: mira flash"}), 404
    return Response(blob, mimetype="application/octet-stream")


@app.route("/api/action/<name>", methods=["POST"])
def api_action(name):
    global _pending_cmd
    if name not in ("upload", "reset", "test-mira", "clear-log", "update-agent",
                    "self-test", "play-music", "test-screen", "test-mic"):
        return jsonify({"error": "unknown action"}), 400
    if name == "clear-log":
        with log_lock:
            log_entries.clear()
        return jsonify({"ok": True})
    with _cmd_lock:
        _pending_cmd = {"name": name, "ts": datetime.now().strftime("%H:%M:%S")}
    return jsonify({"ok": True, "queued": name})

@app.route("/api/set-wifi", methods=["POST"])
def api_set_wifi():
    global _pending_cmd
    data = request.json or {}
    ssid = (data.get("ssid") or "").strip()
    password = data.get("password") or ""
    if not ssid:
        return jsonify({"error": "ssid required"}), 400
    with _cmd_lock:
        _pending_cmd = {
            "name": "set-wifi",
            "params": {"ssid": ssid, "password": password},
            "ts": datetime.now().strftime("%H:%M:%S"),
        }
    return jsonify({"ok": True})

@app.route("/api/stream")
def api_stream():
    def generate():
        last_seq = -1
        while True:
            with log_lock:
                new = [e for e in log_entries if e.get("seq", 0) > last_seq]
            if new:
                last_seq = new[-1]["seq"]
                for e in new:
                    yield f"data: {json.dumps(e, ensure_ascii=False)}\n\n"
            time.sleep(0.3)
    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# ── Web UI ────────────────────────────────────────────────────
@app.route("/")
def index():
    return _HTML

_HTML = (pathlib.Path(__file__).parent / "dashboard.html").read_text(encoding="utf-8")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
