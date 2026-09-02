# HealthCare AI Deployment Guide (A to Z)

This project now supports portable paths and Docker deployment.

## 1) Local Run (Quick Verify)

1. Create and activate virtualenv.
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```
2. Install packages.
```powershell
pip install -r requirements.txt
```
3. Set environment variables in `.env`.
```env
SECRET_KEY=change_me_strong_secret
GROQ_API_KEY=...
GROQ_MODEL=openai/gpt-oss-20b
GOOGLE_API_KEY=...
OPENROUTER_API_KEY=...
```
4. Run:
```powershell
python main.py
```
5. Open `http://localhost:8000`

## 2) Docker Run (Local)

1. Build and run:
```powershell
docker compose up --build
```
2. Open `http://localhost:8000`
3. Persistent data:
- SQLite DB: `./artifacts/data/healthcare.db`
- Upload files: `./uploads`

## 3) Free Deploy Option A (Render Free + Docker)

Best for demos/hobby usage. Not ideal for permanent uploads/SQLite because free instances can spin down and filesystem is ephemeral.

1. Push this repo to GitHub.
2. Create Render account and create a new `Web Service`.
3. Connect repo.
4. Use these settings:
- Environment: `Docker`
- Branch: `main` (or your branch)
- Plan/Instance: `Free`
- Port: `8000`
5. Add environment variables in Render dashboard:
- `SECRET_KEY`
- `GROQ_API_KEY` (optional)
- `GOOGLE_API_KEY` (optional)
- `OPENROUTER_API_KEY` (optional)
- `PORT=8000`
- `HOST=0.0.0.0`
6. Deploy and open the generated Render URL.

Important for your OCR/upload feature on Render Free:
- Upload files and local SQLite may be lost on restart/redeploy/spin-down.
- Use Render only for testing/demo unless you move DB/files to managed storage.

## 4) Free Deploy Option B (Oracle Cloud Always Free VM + Docker) Recommended

Best truly free long-running option for this project with OCR + document uploads.

1. Create Oracle Cloud Free Tier account.
2. Create an `Always Free` Ubuntu VM in your home region.
3. Open inbound ports in security list:
- `22` (SSH)
- `80` (HTTP)
- `443` (HTTPS, optional)
- `8000` (if testing directly)
4. SSH into VM.
```bash
ssh ubuntu@<YOUR_VM_PUBLIC_IP>
```
5. Install Docker + Compose plugin:
```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin git
sudo usermod -aG docker $USER
newgrp docker
```
6. Clone your repo:
```bash
git clone <YOUR_REPO_URL>
cd <REPO_FOLDER>
```
7. Create `.env`:
```bash
cp .env.example .env
nano .env
```
Set at least:
```env
SECRET_KEY=change_me_strong_secret
GROQ_API_KEY=...
GROQ_MODEL=openai/gpt-oss-20b
GOOGLE_API_KEY=...
OPENROUTER_API_KEY=...
```
8. Start app:
```bash
docker compose up -d --build
```
9. Check logs:
```bash
docker compose logs -f
```
10. Open app:
- `http://<YOUR_VM_PUBLIC_IP>:8000`

## 5) Optional Domain + HTTPS (Nginx + Certbot)

1. Point domain DNS `A` record to VM IP.
2. Install nginx + certbot:
```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```
3. Nginx reverse proxy config to `127.0.0.1:8000`.
4. Enable HTTPS:
```bash
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
```

## 6) Production Notes for OCR + Upload

1. Keep `uploads` directory mounted as persistent volume (already in `docker-compose.yml`).
2. Keep SQLite DB under persistent volume (`./artifacts/data` mounted to `/app/data`).
3. For higher reliability later, move from SQLite to managed Postgres and use object storage (S3-compatible).

## 7) Common Fixes

1. App not opening:
- Ensure `PORT` and service port mapping are both `8000`.
2. OCR not reading images:
- Confirm container includes Tesseract (Dockerfile already installs `tesseract-ocr`).
3. Upload fails:
- Check max size is `10MB`.
- Allowed formats: `PDF, JPG, JPEG, PNG, BMP, TIFF, DOC, DOCX, TXT`.
4. Auth errors:
- Set a non-empty `SECRET_KEY`.

## 8) Railway/Fly.io Status (as of May 16, 2026)

- Railway: free trial/credits model, not a stable always-free production tier.
- Fly.io: free trial model, not a stable always-free production tier.

For long-term free hosting of this exact OCR+upload app, Oracle Always Free VM is the strongest option.
