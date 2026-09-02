# OmniVoice Kaggle Worker

This directory contains the Kaggle GPU worker script for executing OmniVoice TTS requests.

## How it works

1. Runs on Kaggle's GPU kernels (e.g. T4 x2 or P100).
2. Register itself to the Lightning AI FastAPI gateway at startup.
3. Loads the OmniVoice model once in GPU memory.
4. Periodically polls the FastAPI server for queued TTS or voice design jobs.
5. Securely downloads reference audio sample if needed.
6. Performs TTS processing.
7. Uploads output `.wav` files back to the gateway.
8. Automatically terminates if no jobs are received for an extended timeout period.

## Files

- `worker.py`: The main python worker script.
- `requirements.txt`: Python package requirements.
- `kernel-metadata.json.example`: Metadata structure for Kaggle API client push.

## Configuration (Kaggle Environment)

You should set the following environment variables (or add them via Kaggle Secrets/code initialization):

- `PUBLIC_API_BASE_URL`: Public address of your FastAPI backend (e.g., `https://xxxx-8000.p.lightning.ai`). Do NOT include trailing slash.
- `WORKER_TOKEN`: Must match the token configured on the FastAPI server to bypass the secure authentication layer.
- `WORKER_ID`: Optional unique ID (e.g. `kaggle-worker-01`).
- `WORKER_IDLE_TIMEOUT_SECONDS`: Duration in seconds to wait for new jobs before shutdown (default: 600).
- `WORKER_POLL_INTERVAL_SECONDS`: Polling frequency (default: 3).

## Deploying using Kaggle CLI

1. Install Kaggle CLI locally:
   ```bash
   pip install kaggle
   ```
2. Set up your `~/.kaggle/kaggle.json` credentials.
3. Copy `kernel-metadata.json.example` to `kernel-metadata.json` and customize the `id` field with your Kaggle username.
4. Push the worker kernel code to Kaggle:
   ```bash
   kaggle kernels push -p .
   ```
