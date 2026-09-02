"""
Smart Nest Web Server
=====================
A Flask web server that connects with an ESP32 dev module to:
    - Control a servo motor for food dispensing
    - Control a relay pump for water dispensing
  - Read DHT22 sensor (temperature & humidity)
  - Detect motion via PIR sensor
  - Capture and serve camera images on motion detection

Communication flow:
  - ESP32 POSTs sensor data to /api/sensor
    - ESP32 polls /api/command for servo commands
    - ESP32 polls /api/pump_command for pump commands
  - ESP32-CAM polls /api/camera_command for capture commands
  - ESP32-CAM uploads captured images to /api/camera/upload
  - Web dashboard / mobile app fetches latest sensor data via /api/data
  - Web dashboard / mobile app fetches images via /api/camera/latest
"""

import os
import io
import threading
import time
import uuid
from datetime import datetime
from flask import Flask, jsonify, render_template, request, send_file
from jinja2 import TemplateNotFound

app = Flask(__name__)

# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------
# Directory to store captured images
CAPTURED_IMAGES_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "captured_images"
)
os.makedirs(CAPTURED_IMAGES_DIR, exist_ok=True)

# ------------------------------------------------------------------
# In-memory data store (latest sensor readings + pending commands)
# ------------------------------------------------------------------
latest_sensor_data = {
    "temperature": None,
    "humidity": None,
    "motion": False,
    "last_update": None,
    "esp32_online": False,
}

# Queue of pending servo commands for the ESP32 to pick up
command_queue = []
command_lock = threading.Lock()

# Queue of pending pump commands for the ESP32 to pick up
pump_command_queue = []
pump_command_lock = threading.Lock()

# Camera capture command queue (ESP32-CAM polls this)
camera_command_queue = []
camera_command_lock = threading.Lock()

# Track the latest captured image metadata
latest_captured_image = {
    "filename": None,
    "timestamp": None,
    "motion_triggered": False,
}

# In-memory latest image bytes (do NOT persist to disk)
latest_image_bytes = None
latest_image_lock = threading.Lock()

# Track the last time we queued a capture to avoid rapid re-triggers
last_capture_trigger_time = 0
CAPTURE_COOLDOWN_SECONDS = 5  # Minimum seconds between capture triggers

# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------


@app.route("/")
def index():
    """Serve the dashboard."""
    try:
        return render_template("index.html")
    except TemplateNotFound:
        # Fallback: template not present in the container (e.g. not committed to Space)
        print("[WARN] index.html template not found — returning fallback HTML")
        return (
            "<html><head><title>Smart Nest</title></head>"
            "<body><h1>Smart Nest</h1><p>Dashboard template not found.</p>" \
            "<p>API is still available under /api/*</p></body></html>"
        )


@app.route("/api/sensor", methods=["POST"])
def receive_sensor_data():
    """
    Endpoint the ESP32 calls to report sensor readings.
    Automatically queues a camera capture command when motion is detected.
    """
    global latest_sensor_data, last_capture_trigger_time

    data = request.get_json(silent=True) or {}
    motion_detected = bool(data.get("motion", False))

    latest_sensor_data = {
        "temperature": data.get("temperature"),
        "humidity": data.get("humidity"),
        "motion": motion_detected,
        "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "esp32_online": True,
    }

    # Auto-queue camera capture when motion is detected (with cooldown)
    if motion_detected:
        now = time.time()
        if now - last_capture_trigger_time >= CAPTURE_COOLDOWN_SECONDS:
            last_capture_trigger_time = now
            with camera_command_lock:
                # Don't queue if there's already a pending capture
                has_pending = any(
                    cmd.get("action") == "capture"
                    for cmd in camera_command_queue
                )
                if not has_pending:
                    camera_command_queue.append({
                        "action": "capture",
                        "timestamp": now,
                        "trigger": "motion"
                    })
                    print(
                        "[CAMERA] Capture queued (motion triggered) at "
                        f"{datetime.now().strftime('%H:%M:%S')}"
                    )

    return jsonify({"status": "ok"})


@app.route("/api/data", methods=["GET"])
def get_sensor_data():
    """Endpoint the dashboard polls to get the latest sensor data."""
    return jsonify(latest_sensor_data)


@app.route("/api/command", methods=["POST"])
def send_command():
    """Endpoint the dashboard calls to queue a food dispense action."""
    data = request.get_json(silent=True) or {}
    action = data.get("action")

    if action not in (None, "dispense_food"):
        return jsonify(
            {
                "status": "error",
                "message": "Unsupported action. Use 'dispense_food'.",
            }
        ), 400

    with command_lock:
        command_queue.append({"action": "dispense_food", "timestamp": time.time()})

    return jsonify(
        {"status": "ok", "message": "Food dispense queued"}
    )


@app.route("/api/command", methods=["GET"])
def get_command():
    """Endpoint the ESP32 polls to fetch pending food dispense commands."""
    with command_lock:
        if command_queue:
            command = command_queue.pop(0)
            return jsonify({"status": "ok", "command": command})
        return jsonify({"status": "ok", "command": None})


@app.route("/api/pump", methods=["POST"])
def send_pump_command():
    """Endpoint the dashboard calls to queue a water dispense command."""
    data = request.get_json(silent=True) or {}
    duration_ms = data.get("duration_ms", 5000)

    try:
        duration_ms = int(duration_ms)
    except (TypeError, ValueError):
        return jsonify(
            {"status": "error", "message": "'duration_ms' must be an integer"}
        ), 400

    if not (1000 <= duration_ms <= 30000):
        return jsonify(
            {
                "status": "error",
                "message": "'duration_ms' must be between 1000 and 30000",
            }
        ), 400

    with pump_command_lock:
        pump_command_queue.append(
            {"duration_ms": duration_ms, "timestamp": time.time()}
        )

    return jsonify(
        {
            "status": "ok",
            "message": f"Water dispense queued: {duration_ms} ms",
        }
    )


@app.route("/api/pump_command", methods=["GET"])
def get_pump_command():
    """Endpoint the ESP32 polls to fetch pending pump commands."""
    with pump_command_lock:
        if pump_command_queue:
            command = pump_command_queue.pop(0)
            return jsonify({"status": "ok", "command": command})
        return jsonify({"status": "ok", "command": None})


# ------------------------------------------------------------------
# Camera routes
# ------------------------------------------------------------------


@app.route("/api/camera_command", methods=["GET"])
def get_camera_command():
    """
    Endpoint the ESP32-CAM polls to fetch pending camera commands.
    Returns a capture command if one is queued.
    """
    with camera_command_lock:
        if camera_command_queue:
            command = camera_command_queue.pop(0)
            return jsonify({"status": "ok", "command": command})
        return jsonify({"status": "ok", "command": None})


@app.route("/api/camera/upload", methods=["POST"])
def receive_camera_image():
    """
    Endpoint the ESP32-CAM calls to upload a captured image.
    Accepts uploads in several common formats and keeps image in memory only:
      - multipart/form-data file fields (any field name)
      - raw image bytes (content-type image/* or application/octet-stream)
      - JSON body with base64 string in `image`/`photo`/`data`
    """
    image_bytes = None

    # 1) Multipart/form-data: accept any uploaded file field
    if request.files:
        try:
            # take the first file provided
            file_storage = next(iter(request.files.values()))
            image_bytes = file_storage.read()
        except Exception as e:
            return jsonify({"status": "error", "message": f"Failed to read uploaded file: {e}"}), 400

    # 2) Raw bytes upload (ESP32 sometimes posts raw JPEG body)
    if image_bytes is None:
        content_type = (request.content_type or "").lower()
        if content_type.startswith("image/") or content_type == "application/octet-stream":
            image_bytes = request.get_data() or None

    # 3) JSON with base64 image payload
    if image_bytes is None:
        data = request.get_json(silent=True)
        if data:
            b64 = data.get("image") or data.get("photo") or data.get("data")
            if b64:
                try:
                    import base64

                    image_bytes = base64.b64decode(b64)
                except Exception as e:
                    return jsonify({"status": "error", "message": f"Invalid base64 image: {e}"}), 400

    if not image_bytes:
        return jsonify({"status": "error", "message": "No image data found in request"}), 400

    # Store latest image in memory (do not write to disk)
    with latest_image_lock:
        global latest_image_bytes, latest_captured_image
        latest_image_bytes = image_bytes
        latest_captured_image = {
            "filename": "latest",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "motion_triggered": True,
            "size": len(image_bytes),
        }

    print(f"[CAMERA] Received image in-memory ({len(image_bytes)} bytes)")

    return jsonify({"status": "ok", "message": "Image received (not stored)", "filename": "latest"})


@app.route("/api/camera/test_upload", methods=["POST"])
def camera_test_upload():
    """
    Lightweight test endpoint for quickly validating uploads (curl or ESP32).
    Accepts raw bytes or multipart/form-data and returns JSON with byte size.
    """
    image_bytes = None

    if request.files:
        try:
            file_storage = next(iter(request.files.values()))
            image_bytes = file_storage.read()
        except Exception as e:
            return jsonify({"status": "error", "message": f"Failed to read uploaded file: {e}"}), 400

    if image_bytes is None:
        content_type = (request.content_type or "").lower()
        if content_type.startswith("image/") or content_type == "application/octet-stream":
            image_bytes = request.get_data() or None

    if not image_bytes:
        return jsonify({"status": "error", "message": "No image data found in request"}), 400

    return jsonify({"status": "ok", "message": "test upload received", "bytes": len(image_bytes)})


@app.route("/api/camera/latest", methods=["GET"])
def get_latest_image_info():
    """
    Returns metadata about the latest captured image.
    The mobile app can use this to construct the image URL.
    """
    return jsonify({
        "status": "ok",
        "image": latest_captured_image,
    })


@app.route("/api/camera/images", methods=["GET"])
def list_camera_images():
    """
    List all captured images, newest first.
    Supports pagination with 'limit' and 'offset' query params.
    """
    try:
        limit = int(request.args.get("limit", 20))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        limit = 20
        offset = 0

    # No persisted images when running in memory-only mode
    return jsonify({
        "status": "ok",
        "total": 0,
        "offset": offset,
        "limit": limit,
        "images": [],
    })


@app.route("/api/camera/image/<filename>", methods=["GET"])
def serve_camera_image(filename):
    """
    Serve a specific captured image by filename.
    The mobile app uses this URL directly in an <Image> component.
    """
    # Prevent directory traversal
    if ".." in filename or "/" in filename:
        return jsonify(
            {"status": "error", "message": "Invalid filename"}
        ), 400

    # If client requests the special 'latest' image, serve the in-memory bytes
    if filename == "latest":
        with latest_image_lock:
            if not latest_image_bytes:
                return jsonify({"status": "error", "message": "No image available"}), 404
            bio = io.BytesIO(latest_image_bytes)
            bio.seek(0)
            resp = send_file(bio, mimetype="image/jpeg")
            # Prevent caching so clients always fetch the newest 'latest' image
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            resp.headers["Pragma"] = "no-cache"
            resp.headers["Expires"] = "0"
            return resp

    # No persisted images available
    return jsonify({"status": "error", "message": "Image not found"}), 404


@app.route("/api/status", methods=["GET"])
def get_status():
    """Return server + ESP32 connection status."""
    return jsonify(
        {
            "server": "online",
            "esp32_online": latest_sensor_data["esp32_online"],
            "last_update": latest_sensor_data["last_update"],
            "camera_images_count": 0,
        }
    )


@app.route("/api/diag", methods=["GET", "POST"])
def diag():
    """
    Diagnostic endpoint: echoes request metadata and prints a short log line.
    Use this from the outside to confirm requests reach the Flask app/container.
    """
    try:
        headers = {k: v for k, v in request.headers.items()}
    except Exception:
        headers = {}

    info = {
        "method": request.method,
        "path": request.path,
        "args": request.args.to_dict(),
        "headers": headers,
        "remote_addr": request.remote_addr,
    }

    print(f"[DIAG] {request.remote_addr} -> {request.method} {request.path}")

    return jsonify({"status": "ok", "diag": info})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    debug_mode = os.environ.get("DEBUG", "True").lower() in ("1", "true", "yes")
    print(f"[SERVER] Captured images directory: {CAPTURED_IMAGES_DIR}")
    print(f"[SERVER] Starting Smart Nest server on http://0.0.0.0:{port}")
    # Run on all interfaces so the ESP32 on the same network can reach it.
    app.run(host="0.0.0.0", port=port, debug=debug_mode)