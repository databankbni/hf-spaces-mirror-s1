---
title: Chatbot
emoji: 💬
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
short_description: AllOfTech RAG chatbot demo API
---

# AllOfTech Multi-Format Vector RAG Chatbot (API-first)

A FastAPI backend that indexes PDF, CSV, and TXT files from the `data` folder into a persistent Chroma vector store, then answers questions with Groq through LangChain. Built to be consumed by your own frontend and hosted as a Docker Space on Hugging Face.

Includes guardrails (prompt-injection blocking, secret redaction), per-session conversation memory, deterministic lead capture with EmailJS submission, pipeline hooks, RAG metrics, and per-IP rate limiting.

## Endpoints

- `GET /health` — health check + active session count
- `POST /chat/stream` — streaming answer (plain text chunks). Body: `{"query": "...", "session_id": "..."}` (session ID optional; returned in the `X-Session-Id` header)
- `POST /chat` — full answer as JSON with sources, lead state, and browser EmailJS payload: `{"answer", "session_id", "sources", "blocked", "lead", "emailjs"}`
- `GET /lead/{session_id}` — current service-request draft for the frontend confirmation card
- `POST /lead/{session_id}/confirm` — return the EmailJS payload for the browser confirm button
- `POST /lead/{session_id}/submitted` — mark the request submitted after browser EmailJS succeeds
- `POST /lead/{session_id}/cancel` — cancel the current request draft
- `DELETE /sessions/{session_id}` — forget a conversation ("New chat")
- `GET /metrics` — RAG metrics (query counts, latency, retrieval quality, guardrail blocks)
- `GET /docs` — interactive Swagger UI

## Run locally

```bash
uv run python main.py
```

The API starts on `http://localhost:7860` by default, or `http://localhost:1111` when `PORT=1111` is set in `.env`.

## Configuration

Set `GROQ_API_KEY` as a Space secret (or in `.env` locally). Optional environment variables: `GROQ_MODEL` (default `openai/gpt-oss-120b`), `DATA_DIR`, `CHROMA_DIR`, `CORS_ORIGINS`, `PORT`, `RATE_LIMIT_PER_MINUTE`, `COMPANY_CONTACT_INFO`, `EMAILJS_PUBLIC_KEY`, `EMAILJS_SERVICE_ID`, `EMAILJS_TEMPLATE_ID`, `EMAILJS_DELIVERY_MODE`, `EMAILJS_PRIVATE_KEY` or `EMAILJS_ACCESS_TOKEN`, `RAG_MAX_CONCURRENT_REQUESTS`, `RAG_QUEUE_TIMEOUT_SECONDS`, `RAG_CACHE_TTL_SECONDS`, and `RAG_SCORE_THRESHOLD`.

## Deploy to Hugging Face Spaces

This project is ready for a Hugging Face Docker Space. Docker Spaces run on CPU by default, which is the right setup for this API because the LLM call goes through Groq and the local embedding model runs on CPU.

1. Install and log in to the Hugging Face CLI:

```bash
pip install -U huggingface_hub
hf auth login
hf auth whoami
```

2. Create the Space. Replace `<username>` and `<space-name>` with your Hugging Face account and desired Space name:

```bash
hf repos create <username>/<space-name> --type space --space-sdk docker --public --exist-ok
```

3. Add required secrets. `GROQ_API_KEY` is required for answers. EmailJS values are optional if you use the defaults in code, but setting them as secrets is recommended for production:

```bash
hf spaces secrets add <username>/<space-name> --secrets GROQ_API_KEY=your_groq_key
hf spaces secrets add <username>/<space-name> --secrets EMAILJS_PUBLIC_KEY=your_emailjs_public_key
hf spaces secrets add <username>/<space-name> --secrets EMAILJS_SERVICE_ID=your_emailjs_service_id
hf spaces secrets add <username>/<space-name> --secrets EMAILJS_TEMPLATE_ID=your_emailjs_template_id
```

4. Add optional public environment variables. Set `CORS_ORIGINS` to your real frontend domain when you connect the website:

```bash
hf spaces variables add <username>/<space-name> --env CORS_ORIGINS=https://www.alloftech.site
hf spaces variables add <username>/<space-name> --env EMAILJS_DELIVERY_MODE=frontend
hf spaces variables add <username>/<space-name> --env RATE_LIMIT_PER_MINUTE=20
```

5. Upload the project files from the repository root:

```bash
hf upload <username>/<space-name> . --type space --exclude ".git/**" --exclude ".cursor/**" --exclude ".env*" --exclude "chroma_db/**" --exclude ".venv/**" --exclude "__pycache__/**"
```

6. Watch build and runtime logs:

```bash
hf spaces logs <username>/<space-name> --build --follow
hf spaces logs <username>/<space-name> --tail 200
```

7. Verify the API after the Space is running:

```bash
curl https://<username>-<space-name>.hf.space/health
curl -X POST https://<username>-<space-name>.hf.space/chat \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"What services does AllOfTech offer?\"}"
```

If the Space is private or protected, call it from your frontend with the proper Hugging Face authentication token. For a public website chatbot, keep the Space public or proxy it through your own backend.

This API is a document RAG chatbot only. It answers questions from indexed PDF, CSV, and TXT files. It does not collect orders, meetings, or contact forms.
