---
title: Call-In Podcast
emoji: 📞
colorFrom: purple
colorTo: green
sdk: docker
sdk_version: latest
app_file: Dockerfile
app_port: 7860
pinned: false
short_description: Two Crusoe LLMs host a live podcast — call in with your mic
---

# 📞 Call-In Podcast

Two LLM hosts improvise a live podcast, and **you are the caller**: just start
talking and they'll take your call on air.

- **Atlas** — NVIDIA Nemotron-3-Ultra-550B on [Crusoe Managed Inference](https://crusoe.ai/managed-inference), voiced by Kokoro `am_michael`
- **Nova** — Zai GLM-5.2 on Crusoe Managed Inference, voiced by Kokoro `af_heart`
- **You** — transcribed locally by Whisper, no audio leaves the box

Everything except the two LLMs runs locally in the Space: Whisper STT, Kokoro
TTS (one instance per host so each has their own voice), and Silero VAD, all
orchestrated by [Pipecat](https://github.com/pipecat-ai/pipecat). The only
secret required is `CRUSOE_API_KEY`.

## Usage

Click **Connect**, allow the mic, and listen. Interrupt any time by speaking —
the hosts stop, take your call, and fold it into the show.

> **Wear headphones.** Without them, Whisper hears the hosts through your mic
> and the show gets phantom callers. (There is an echo-guard heuristic, but
> it's no substitute for headphones.)

## How it works

```
mic ──► Silero VAD ──► Whisper STT ──► ConversationTap ──► Kokoro (Atlas) ──► Kokoro (Nova) ──► speakers
                                            │                    ▲                  ▲
                                    caller transcriptions        └── TTSSpeakFrame ─┘
                                            ▼                             │
                                     PodcastConductor ── Crusoe chat API ─┘
                                     (turn loop: alternate hosts,
                                      fold in callers, barge-in interrupts)
```

The `PodcastConductor` alternates turns between the hosts, calling each host's
model with its own persona and the shared transcript. Each line is spoken via
that host's dedicated `KokoroTTSService`. The `ConversationTap` watches the
pipeline: caller transcriptions trigger an `InterruptionFrame` (barge-in) and
are queued for the next turn; `BotStarted/StoppedSpeakingFrame` tell the
conductor when a host has finished speaking (with a duration-estimate fallback
if those frames never arrive).

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
echo "CRUSOE_API_KEY=your-key" > .env
python bot.py
```

Then open http://localhost:7860 and click Connect.

## Configuration (env vars)

| Variable | Default | Purpose |
| --- | --- | --- |
| `CRUSOE_API_KEY` | — (required) | Crusoe Managed Inference API key |
| `PODCAST_TOPIC` | random fun topic | Episode topic |
| `SHOW_NAME` | Call-In Podcast | Show name the hosts use |
| `HOST_A_MODEL` | nvidia/Nemotron-3-Ultra-550B | Atlas's model |
| `HOST_B_MODEL` | zai/GLM-5.2 | Nova's model |
| `HOST_A_VOICE` / `HOST_B_VOICE` | am_michael / af_heart | Kokoro voices |
| `WHISPER_MODEL` | pipecat default (`base` in Docker) | Local STT model size |
