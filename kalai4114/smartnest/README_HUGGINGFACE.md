How to deploy this Flask backend to Hugging Face Spaces (Docker)

Quick steps:

1. Create a new Space on Hugging Face:
   - Visit https://huggingface.co/spaces and click "Create new Space".
   - Choose a name (e.g. `smart-nest-backend`) and set "SDK" to "Other" or choose "Docker" runtime.
   - Make the Space Public or Private as you prefer.

2. Prepare this repo for the Space:
   - This folder already contains a `Dockerfile` that runs the Flask app with Gunicorn and exposes port `7860`.
   - Ensure `requirements.txt` contains `flask` (already present). The Dockerfile installs `gunicorn`.

3. Push to the Space repository:
   - Initialize git in this folder (or from repo root) and add a remote pointing to your Space. Example:

```bash
cd server
git init
git add .
git commit -m "Add Dockerfile for Hugging Face Space"
# Replace <USERNAME> and <SPACE-NAME> with your values
git remote add origin https://huggingface.co/spaces/<USERNAME>/<SPACE-NAME>
git push origin main
```

4. Wait for the Space build to finish. The Space will run the Dockerfile and start the server.

5. After deployment the Space URL will be https://<USERNAME>.hf.space and the API endpoints will be available under that domain, e.g.:

- `https://<USERNAME>.hf.space/api/camera/latest`
- `https://<USERNAME>.hf.space/api/camera/image/latest`

Notes and caveats:
- Hugging Face Spaces are intended for demo apps and have usage limits for free accounts. For production or heavy usage you may need a paid plan or a different hosting provider.
- Esp32 and mobile app must be able to reach the public Space URL. If you keep using local IPs (192.168.x.x) update `mobile/src/services/api.js` and ESP32 firmware to target the HF Space URL.
- If you need HTTPS endpoints for the ESP32, Spaces serve HTTPS by default.
