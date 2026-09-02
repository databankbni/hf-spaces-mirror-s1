---
title: OmniVoice Gateway
emoji: 🎙️
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
storage: small
---

# OmniVoice On-Demand Gateway

OmniVoice On-Demand Gateway is an MVP system that connects a CPU-bound web application and FastAPI gateway running on Lightning AI with a GPU-bound OmniVoice TTS model running on Kaggle.

It implements a **pull-based worker architecture** where the GPU worker polls the gateway for jobs, processes them sequentially, and pushes the outputs back.

---

## Key Features

1. **Voice Sample Upload**: Upload an audio file (`WAV/MP3/FLAC`) to clone a voice.
2. **Voice Design Preview**: Describe a voice in natural Vietnamese (e.g. *"giọng nữ trẻ trầm ấm"*), generate a 3-second preview, and listen.
3. **Voice Acceptance**: Accept the preview to convert it into a standard reference sample for future TTS jobs.
4. **TTS Generation**: Generate high-fidelity text-to-speech outputs using either `clone_voice`, `auto_voice`, or direct `voice_design` prompts.
5. **Real-time Status Polling**: Tracks progress stages (`queued`, `starting_worker`, `booting_kaggle`, `loading_model`, `generating_audio`, `exporting_wav`, etc.).
6. **Bearer Token Authentication**: Secures worker communication APIs.

---

## Directory Structure

```text
omnivoice-gateway/
├─ backend/             # FastAPI Gateway, SQLite DB, Mock Services
│  ├─ app/
│  │  ├─ main.py        # App Lifespan & Routing Configuration
│  │  ├─ config.py      # Pydantic Settings
│  │  ├─ database.py    # SQLite / SQLAlchemy Init
│  │  ├─ models.py      # DB Models (VoiceSample, TTSJob, WorkerSession...)
│  │  ├─ routers/       # Modular Endpoints (health, jobs, tts...)
│  │  └─ services/      # Job, Audio, and Kaggle Orchestrator Services
├─ frontend/            # React + Vite + TS + Tailwind CSS Dashboard
│  ├─ src/
│  │  ├─ api/client.ts  # HTTP Fetch Client for Gateway
│  │  └─ components/    # Custom Dashboard Panels
└─ kaggle_worker/       # GPU Polling script running OmniVoice
   └─ worker.py         # Polling execution script
```

---

## A. Running Local Mock Mode

In Mock mode, the gateway runs a background thread simulating the transitions and outputs of a GPU worker. It generates standard WAV files containing a pleasant tone.

### 1. Run Backend
1. Open a terminal in `backend/`:
   ```bash
   cd backend
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # Linux/macOS:
   source .venv/bin/activate
   
   pip install -r requirements.txt
   ```
2. Create `.env` from `.env.example`:
   ```bash
   copy .env.example .env
   ```
3. Set `WORKER_MODE=mock`.
4. Start the server:
   ```bash
   uvicorn app.main:app --reload
   ```
   The backend will be available at `http://localhost:8000`.

### 2. Run Frontend
1. Open a terminal in `frontend/`:
   ```bash
   cd frontend
   npm install
   ```
2. Create `.env` from `.env.example`:
   ```bash
   copy .env.example .env
   ```
   *Ensure `VITE_API_BASE_URL=http://localhost:8000`*.
3. Start the dev server:
   ```bash
   npm run dev
   ```
4. Open your browser at `http://localhost:5173`.

---

## B. Production Deployment (Lightning AI + Kaggle GPU)

In production, the backend runs on a Lightning AI CPU instance, and the worker runs on a Kaggle GPU notebook.

### Why Ngrok is Not Needed
Since FastAPI runs on Lightning AI, which exposes ports on a public URL, the Kaggle Worker (running inside Kaggle's environment with internet enabled) can call the gateway directly via its public URL. No Ngrok tunnel is needed!

### 1. Deploy Gateway on Lightning AI
1. Create a CPU/RAM Studio in Lightning AI.
2. Clone this repo into the Studio.
3. Open a terminal in `backend/` and install requirements:
   ```bash
   pip install -r requirements.txt
   ```
4. Create the `.env` file:
   - Set `WORKER_MODE=kaggle`.
   - Set `WORKER_TOKEN=<generate-a-secure-random-token-here>`.
   - Configure Kaggle Credentials:
     ```ini
     KAGGLE_USERNAME=your_kaggle_username
     KAGGLE_KEY=your_kaggle_api_key
     KAGGLE_KERNEL_REF=your_kaggle_username/omnivoice-worker
     KAGGLE_WORKER_DIR=../kaggle_worker
     ```
5. Run the server:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
6. Expose port `8000` in Lightning AI. Copy the generated **Public URL** (e.g., `https://xxxx-8000.p.lightning.ai`).
7. Update the `.env` file on Lightning AI:
   - Set `PUBLIC_API_BASE_URL` to your Public URL (without trailing slash).
   - Set `FRONTEND_ORIGINS` to allow your deployed frontend or localhost.
8. Restart uvicorn.

### 2. Configure and Push Kaggle Worker
1. Install Kaggle CLI locally or on the machine you push from:
   ```bash
   pip install kaggle
   ```
2. Copy `kernel-metadata.json.example` in `kaggle_worker/` to `kernel-metadata.json` and change `id` to your username.
3. Push the kernel to Kaggle:
   ```bash
   kaggle kernels push -p ./kaggle_worker
   ```
4. Ensure the Kaggle kernel has the following environment variables injected (or set them at the top of the notebook script):
   - `PUBLIC_API_BASE_URL=<Your Lightning AI Public URL>`
   - `WORKER_TOKEN=<Your secure worker token>`

Once pushed, the worker will boot up, install `requirements.txt`, load OmniVoice, register with the gateway, and pull jobs!

---

## C. Automatically Create and Push the Kaggle Worker

The system supports an automatic mechanism to build the worker directory and source code based on system configuration parameters entered via `.env` or the Settings panel on the Web Dashboard. This helps run the worker stably in headless mode without needing to interact with the Kaggle Notebook interface.

### Step-by-step workflow:

1. **Set environment variables**: Make sure to fully provide the required information in the `.env` file or update it through the system configuration panel on the Web Dashboard:

   * `KAGGLE_USERNAME`: Kaggle username
   * `KAGGLE_KEY`: Kaggle API Key
   * `KAGGLE_KERNEL_SLUG`: Kernel path ID (Default: `omnivoice-worker`)
   * `KAGGLE_KERNEL_TITLE`: Display title (Default: `OmniVoice Worker`)
   * `PUBLIC_API_BASE_URL`: Public URL of the FastAPI Gateway running on Lightning AI
   * `WORKER_TOKEN`: Shared Bearer token security key between the worker and the gateway

2. **Automatically generate source code (Prepare Worker)**:

   ```bash
   python backend/scripts/prepare_kaggle_worker.py
   ```

   This command will automatically create the `kaggle_worker` directory if it does not already exist, generate the `kernel-metadata.json`, `requirements.txt`, and the headless execution script `worker.py`, which includes the built-in dependency checking and auto-installation function `ensure_dependencies()`.

3. **Push the Worker to Kaggle (Push Worker)**:

   ```bash
   python backend/scripts/push_kaggle_worker.py
   ```

   This command will call the Kaggle CLI to push the source code to a Kaggle Kernel, with the default Accelerator configuration set to GPU `NvidiaTeslaT4` or another configuration value defined in the environment variables.
   After the push is successful, Kaggle will automatically start a GPU instance and run the worker.

4. **Automatic activation (Automated push)**:
   If the backend is running in `WORKER_MODE=kaggle` and there is currently no active worker, the FastAPI gateway will automatically trigger this prepare-and-push process when it receives the first TTS job from a user.

---

## D. Word-Level Alignment API Guide (Opt-in)

The gateway supports returning precise word-level start/end timestamps (in seconds) to automate caption synchronization.

### 1. Request Schema (`POST /v1/audio/speech`)
This is an OpenAI-compatible speech endpoint. Add `with_alignment: true` to get the word timestamps.

**Headers:**
```http
Authorization: Bearer <your_jwt_token_or_api_key>
Content-Type: application/json
```

**Body:**
```json
{
  "model": "omnivoice",
  "input": "Hệ thống OmniVoice đang chạy",
  "voice": "female, young adult, american accent",
  "with_alignment": true
}
```

### 2. Response Schema
When `with_alignment` is `true`, instead of returning the raw binary audio file, the API returns a structured JSON payload:

```json
{
  "status": "completed",
  "audioUrl": "https://<your-gateway-host>/v1/tts/jobs/job_xxxxxx/audio",
  "duration": 2.05,
  "alignment": [
    { "word": "Hệ", "start": 0.0, "end": 0.68 },
    { "word": "thống", "start": 0.68, "end": 1.36 },
    { "word": "OmniVoice", "start": 1.36, "end": 2.05 }
  ]
}
```

> [!NOTE]
> By default, `with_alignment` is `false`. The API will return the raw audio binary file directly, saving GPU/CPU resources on the worker nodes.

---

## E. Voice Library API

The gateway provides a Voice Library system for managing and browsing voice samples. Public voices can be listed without authentication, making it easy for clients to browse and select voices.

### 1. List Public Voices — `GET /v1/voice-library`

**No authentication required.** Browse all public voice samples with optional filtering.

**Query Parameters:**

| Param    | Type   | Default | Description                          |
|----------|--------|---------|--------------------------------------|
| `tag`    | string | —       | Filter by tag (e.g., `Miền Bắc`)     |
| `search` | string | —       | Search by voice name                 |
| `limit`  | int    | 50      | Maximum number of results (1-200)    |
| `offset` | int    | 0       | Pagination offset                    |

**Response:**
```json
[
  {
    "id": "vs_abc123",
    "name": "Giọng nữ trầm ấm",
    "tags": ["Miền Bắc", "Trẻ", "Kể chuyện"],
    "ref_text": "Xin chào, tôi là...",
    "duration": 7.5,
    "is_public": true,
    "preview_url": "/v1/voice-samples/vs_abc123/audio",
    "source_job_data": {
      "mode": "clone_voice",
      "speed": 1.0,
      "num_step": 32,
      "guidance_scale": 2.0
    },
    "created_at": "2025-06-01T12:00:00"
  }
]
```

### 2. Preview Audio — `GET /v1/voice-samples/{id}/audio`

Returns the WAV audio file of a voice sample. Public voices don't require authentication.

### 3. Edit Voice Sample — `PUT /v1/voice-samples/{id}`

**Requires Bearer token.** Updates name, tags, ref_text, or is_public of a user's own voice sample.

**Request Body:**
```json
{
  "name": "Giọng nữ mới",
  "tags": ["Miền Nam", "Quảng cáo"],
  "ref_text": "Văn bản tham khảo mới...",
  "is_public": false
}
```

All fields are optional. Only provided fields will be updated.

### 4. Available Tags

Voice samples support custom tags for classification. Common preset tags include:

| Category   | Tags                                |
|-----------|-------------------------------------|
| Region    | `Miền Bắc`, `Miền Nam`, `Miền Trung` |
| Age       | `Trẻ`, `Trung niên`, `Cao tuổi`      |
| Style     | `Kể chuyện`, `Quảng cáo`, `Tin tức`, `Podcast`, `Audiobook` |

Custom tags can also be added freely.

<!-- Trigger rebuild: 2026-07-21 10:59 -->
