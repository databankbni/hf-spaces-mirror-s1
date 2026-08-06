# SuperAGI Chat Backend

Small Python chat API for the `/chat` frontend.

It exposes:

- `GET /`
- `GET /health`
- `POST /api/chat`
- `GET /api/chat/sessions/<session_id>`
- `GET /api/models/active`

Run locally:

```bash
npm run dev:chat-backend
```

By default it listens on `127.0.0.1:5001` and persists chat sessions to
`python_backend/data/chat.sqlite3`.

Override those with:

```bash
SUPERAGI_HOST=0.0.0.0 SUPERAGI_PORT=5001 SUPERAGI_CHAT_DB=/var/lib/superagi/chat.sqlite3 npm run dev:chat-backend
```

For deployed storage, set `SUPABASE_DATABASE_URL` on the backend. When that
variable exists, the backend writes chat sessions and training examples to
Postgres and mirrors them to local SQLite. If Supabase is paused or otherwise
unreachable, the backend serves chat from local SQLite instead of failing the
request.

For this Supabase project on the free plan, use the IPv4 session-pooler URL:

```bash
SUPABASE_DATABASE_URL='postgresql://postgres.jscgykqjejcfdfnihizw:<URL-ENCODED-PASSWORD>@aws-0-eu-west-1.pooler.supabase.com:5432/postgres?sslmode=require' \
npm run dev:chat-backend
```

The direct URL also works on networks/hosts that can reach Supabase's IPv6
database endpoint:

```bash
SUPABASE_DATABASE_URL='postgresql://postgres:<URL-ENCODED-PASSWORD>@db.jscgykqjejcfdfnihizw.supabase.co:5432/postgres?sslmode=require'
```

`DATABASE_URL` also works, but `SUPABASE_DATABASE_URL` is clearer for this app.
Keep this value server-side only. For local development, export it in your
shell before starting the backend, or store it in an ignored `.env` file and
source that file yourself. For Hugging Face, add it as a Space secret. If the
password contains symbols like `@`, `:`, `/`, or `#`, URL-encode it before
putting it into the connection string.

The backend auto-creates the required tables on first use. You can also run
`python_backend/migrations/001_chat_storage.sql` in the Supabase SQL editor to
create them explicitly.

## Keeping Supabase Free Projects Active

Supabase free projects pause after inactivity. This repo includes a scheduled
GitHub Actions heartbeat in `.github/workflows/keep-supabase-awake.yml` that
queries `chat_sessions` every Monday and Thursday.

Add these repository secrets in GitHub:

```bash
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<server-side-service-role-key>
```

The workflow uses the service role key server-side only and can also be run
manually from GitHub Actions after creating a new Supabase project.

## RunPod Serverless inference

The backend can keep handling chat sessions and storage while sending only model
inference to a RunPod Serverless endpoint. When both values are present, the
backend routes all model labels to the configured RunPod endpoint and stores
the requested model label with the conversation:

```bash
RUNPOD_API_KEY=<server-side-api-key> \
RUNPOD_ENDPOINT_ID=<endpoint-id> \
RUNPOD_TIMEOUT_SECONDS=180 \
SUPERAGI_MAX_NEW_TOKENS=120 \
SUPERAGI_TEMPERATURE=0.5 \
npm run dev:chat-backend
```

Optional settings:

```bash
RUNPOD_BASE_URL=https://api.runpod.ai/v2
SUPERAGI_TOP_K=20
SUPERAGI_REPETITION_PENALTY=1.25
SUPERAGI_REPETITION_WINDOW=128
```

Keep `RUNPOD_API_KEY` server-side only. If either `RUNPOD_API_KEY` or
`RUNPOD_ENDPOINT_ID` is missing, the backend falls back to its bundled local
checkpoint runner.

Run the production server locally:

```bash
PYTHONPATH=python_backend python3 -m pip install -r python_backend/requirements.txt
PYTHONPATH=python_backend PORT=7860 SUPERAGI_HOST=0.0.0.0 python3 -m superagi_backend.production
```

Build and run the Hugging Face-style Docker image:

```bash
make docker-build
make docker-run
curl http://127.0.0.1:7860/health
```

The Docker image installs the model runtime dependencies by default.
To skip them for a smaller placeholder-only image:

```bash
docker build --build-arg INSTALL_SUPERAGI_DEPS=false -t superagi-chat-backend .
```

For Hugging Face Spaces, create a Docker Space, copy `huggingface.README.md`
to the Space repo as `README.md`, and include the root `Dockerfile`,
`python_backend/`, and any model files/source needed by the runner.

Use a trained SuperAGI checkpoint for the current `SuperAGI 0.2` runner:

```bash
python3 -m pip install -r /path/to/SuperAGI/requirements.txt

SUPERAGI_REPO_PATH=/path/to/SuperAGI \
SUPERAGI_CHECKPOINT_PATH=/path/to/SuperAGI/prod/night-0606/best.pt \
SUPERAGI_DEVICE=auto \
SUPERAGI_MAX_NEW_TOKENS=120 \
SUPERAGI_TEMPERATURE=0.5 \
SUPERAGI_TOP_K=20 \
SUPERAGI_REPETITION_PENALTY=1.25 \
SUPERAGI_REPETITION_WINDOW=128 \
npm run dev:chat-backend
```

The chat API accepts `SuperAGI 0.2` as the current chat-able model label. The
frontend still shows deprecated and coming-soon model cards, but it does not
send those labels to the backend. The stored conversation and training example
keep the requested model label.

To configure the current `SuperAGI 0.2` checkpoint, set model-specific env vars:

```bash
SUPERAGI_0_2_REPO_PATH=/path/to/SuperAGI \
SUPERAGI_0_2_CHECKPOINT_PATH=/path/to/superagi-0.3.pt \
npm run dev:chat-backend
```

If you bundle that checkpoint in this repo, put it at:

```bash
python_backend/models/superagi/superagi-0.3.pt
```

For compatibility with the previous public `SuperAGI 0.3` label, the backend
also checks these legacy env vars for the current shifted `SuperAGI 0.2`
runner:

```bash
SUPERAGI_0_3_REPO_PATH=/path/to/SuperAGI \
SUPERAGI_0_3_CHECKPOINT_PATH=/path/to/superagi-0.3.pt \
npm run dev:chat-backend
```

If you bundle that checkpoint in this repo, put it at:

```bash
python_backend/models/superagi/superagi-0.3.pt
```

Inside the Docker image, model dependencies are installed by default. If you
override `INSTALL_SUPERAGI_DEPS=false`, the backend can still start, but the
real checkpoint runner will fail until the dependencies are present.

If you copy checkpoints into this repo, use `python_backend/models/`.
Git LFS is configured for common model artifact extensions in that directory,
including `.pt`, `.pth`, `.bin`, `.gguf`, and `.safetensors`.

Historical checkpoint paths may still exist in local clones, but the current
backend only routes to:

```bash
python_backend/models/superagi/superagi-0.3.pt
```

Example chat request:

```bash
curl -X POST http://127.0.0.1:5001/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "browser-session-1",
    "model": "SuperAGI 0.2",
    "messages": [
      {
        "role": "assistant",
        "text": "Hi. This chat window is ready for the AI backend."
      }
    ],
    "message": "What can you do?"
  }'
```

The backend stores chat context by `session_id`. If a request omits `messages`
or sends an empty context for an existing session, the backend loads the
persisted messages before generating the next reply.

Every successful chat turn is also appended to `training_examples` with the
session id, model, user text, assistant text, prompt, and context JSON. This is
the durable log intended for later model-training exports. `chat_messages` is
only the latest session snapshot used to restore the chat UI. Use Supabase for
deployment if you do not want this data tied to the lifetime of the backend
container.

When `python_backend/vendor/SuperAGI` and
`python_backend/models/superagi/superagi-0.3.pt` are present, the backend loads
that bundled checkpoint as the current `SuperAGI 0.2` runner automatically.
Without a bundled or configured checkpoint, the model uses a placeholder runner
behind the same API contract.
