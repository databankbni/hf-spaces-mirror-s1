---
title: Smart Nest Backend
emoji: 🏡
colorFrom: blue
colorTo: green
sdk: docker
sdk_version: "docker"
python_version: "3.10"
app_file: app.py
pinned: false
license: mit
app_port: 7860
---

Smart Nest backend — a lightweight Flask API to interact with ESP32 devices, serve sensor data, and provide the latest in-memory camera image for mobile clients.

Features

- REST endpoints for sensor telemetry, servo/pump commands, and camera capture/upload.
- Keeps the latest camera upload in memory (no disk persistence) and serves it at `/api/camera/image/latest` with no-cache headers.
- Simple command queues for the ESP32 to poll (`/api/command`, `/api/pump_command`, `/api/camera_command`).
- Test upload endpoint (`/api/camera/test_upload`) for quick curl/ESP32 validation.

Quick start (local)

```bash
# from the server folder
python -m venv .venv
source .venv/Scripts/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Docker (recommended for Hugging Face Spaces)

```bash
# build
docker build -t smart-nest-backend .
# run locally (exposes port 7860 like the Space runtime)
docker run -p 7860:7860 -e PORT=7860 smart-nest-backend
```

API highlights

- `GET /api/data` — latest sensor data (temperature, humidity, motion)
- `POST /api/command` — queue a food dispense (`{ "action": "dispense_food" }`)
- `GET /api/command` — ESP32 polls for pending servo commands
- `POST /api/pump` — queue a water dispense (`{ "duration_ms": 5000 }`)
- `GET /api/pump_command` — ESP32 polls for pending pump commands
- `GET /api/camera_command` — ESP32-CAM polls for capture commands
- `POST /api/camera/upload` — ESP32-CAM uploads raw/multipart/base64 image bytes (stored in-memory)
- `POST /api/camera/test_upload` — quick test upload endpoint (returns byte count)
- `GET /api/camera/latest` — metadata for the latest image (timestamp/size)
- `GET /api/camera/image/latest` — returns the latest image bytes with no-cache headers

Important notes

- The server intentionally keeps the latest camera image in memory and does not write images to disk. This is by design to avoid persisting photos in the Space storage.
- After deploying to a public Space you must update the mobile app `BASE_URL` in `mobile/src/services/api.js` and the ESP32 firmware upload URL to point at `https://<USERNAME>.hf.space`.
- Hugging Face Spaces run on HTTPS; ensure your ESP32 firmware supports HTTPS or use a network-accessible HTTP proxy if testing from local devices.

Testing upload via curl

```bash
# raw JPEG body
curl --data-binary @photo.jpg -H "Content-Type: image/jpeg" https://<USERNAME>.hf.space/api/camera/test_upload

# metadata check
curl https://<USERNAME>.hf.space/api/camera/latest

# fetch latest image
curl -v https://<USERNAME>.hf.space/api/camera/image/latest -o latest.jpg
```

Deploy to Hugging Face Spaces

1. Create a new Space (SDK = Docker) on https://huggingface.co/spaces.
2. Push the `server` folder contents to the Space git remote (see `README_HUGGINGFACE.md` for exact commands).
3. Update clients (mobile app and ESP32) to point to the deployed Space URL.

Security & Limits

- Spaces are intended for demos — consider traffic limits, privacy, and retention needs before production.
- If you want persistent image storage, mount an external storage bucket or adapt the server to write to disk (not recommended on Spaces without storage).

See also

- `README_HUGGINGFACE.md` — step-by-step deploy notes
- `Dockerfile` — container image used by the Space

If you'd like, I can also:

- Fill in the Space `title`/`emoji`/colors differently.
- Update `mobile/src/services/api.js` with the Space URL and create a commit ready to push.
