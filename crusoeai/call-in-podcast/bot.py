"""Call-In Podcast — two Crusoe-hosted LLMs run a live podcast you can call into.

Two customizable hosts (name, personality, Crusoe model, Kokoro voice)
improvise a podcast episode on any topic. Call in by voice (mic barge-in) or
by text, and the hosts fold you into the show. Whisper STT, Kokoro TTS (one
Pipecat service per host), and Silero VAD all run locally; the only API key
required is CRUSOE_API_KEY.

Run:
    python bot.py

Then open http://localhost:7860. Wear headphones — without them the hosts
hear themselves through your mic and take phantom calls.
"""

import asyncio
import json
import os
import random
import re
import time
import uuid
from collections import deque
from dataclasses import dataclass, field

import numpy as np
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, StreamingResponse
from kokoro_onnx import Kokoro
from loguru import logger
from openai import AsyncOpenAI

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    SpeechOutputAudioRawFrame,
    TranscriptionFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.runner.types import WebSocketRunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.serializers.protobuf import ProtobufFrameSerializer
from pipecat.services.kokoro.tts import KOKORO_CACHE_DIR, _ensure_model_files
from pipecat.services.whisper.stt import WhisperSTTService
from pipecat.transports.base_transport import BaseTransport
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams
from pipecat.workers.runner import WorkerRunner

load_dotenv(override=True)

CRUSOE_API_BASE = os.environ.get("CRUSOE_API_BASE", "https://api.inference.crusoecloud.com/v1")
SHOW_NAME = os.environ.get("SHOW_NAME", "Call-In Podcast")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# English voices shipped in kokoro-onnx voices-v1.0.bin (Pipecat's Kokoro model cache).
KOKORO_VOICES = {
    "af_heart": "Heart — US female",
    "af_bella": "Bella — US female",
    "af_nova": "Nova — US female",
    "af_sarah": "Sarah — US female",
    "af_sky": "Sky — US female",
    "af_alloy": "Alloy — US female",
    "af_aoede": "Aoede — US female",
    "af_jessica": "Jessica — US female",
    "af_kore": "Kore — US female",
    "af_nicole": "Nicole — US female (whispery)",
    "af_river": "River — US female",
    "am_michael": "Michael — US male",
    "am_adam": "Adam — US male",
    "am_echo": "Echo — US male",
    "am_eric": "Eric — US male",
    "am_fenrir": "Fenrir — US male",
    "am_liam": "Liam — US male",
    "am_onyx": "Onyx — US male",
    "am_puck": "Puck — US male",
    "bf_alice": "Alice — UK female",
    "bf_emma": "Emma — UK female",
    "bf_isabella": "Isabella — UK female",
    "bf_lily": "Lily — UK female",
    "bm_daniel": "Daniel — UK male",
    "bm_fable": "Fable — UK male",
    "bm_george": "George — UK male",
    "bm_lewis": "Lewis — UK male",
}

# Per-host defaults; everything except the color is overridable per episode.
HOST_DEFAULTS = {
    "a": {
        "name": "Atlas",
        "color": "#a78bfa",
        "voice": os.environ.get("HOST_A_VOICE", "am_michael"),
        "model_needles": ["nemotron-3-ultra", "nemotron-3-super", "nemotron"],
        "model": os.environ.get("HOST_A_MODEL", "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B"),
        "personality": (
            "Enthusiastic deep-diver. Goes on fascinating tangents, connects "
            "unexpected dots, says 'here's the wild part' a lot. Warm with callers."
        ),
    },
    "b": {
        "name": "Nova",
        "color": "#34d399",
        "voice": os.environ.get("HOST_B_VOICE", "af_heart"),
        "model_needles": ["glm-5.2", "glm"],
        "model": os.environ.get("HOST_B_MODEL", "zai/GLM-5.2"),
        "personality": (
            "Sharp, witty reactor. Keeps things grounded with humor, challenges "
            "bold claims, asks the questions the audience is thinking. Punchy."
        ),
    },
}

FALLBACK_TOPICS = [
    "why great ideas always arrive in the shower",
    "the secret economics of vending machines",
    "what cities would look like if they were designed by ants",
    "the strange history of the snooze button",
    "why every technology eventually becomes a toaster",
]

INSPIRE_CATEGORIES = [
    "funny", "techy", "deep", "business", "weird", "science", "history", "pop-culture",
]

# Instructions injected every few turns to keep the conversation dynamic,
# adapted from FakePod's variety prompts for short spoken turns.
VARIETY_PROMPTS = [
    "Play devil's advocate on the last point. Be provocative but fun.",
    "Share a surprising real-world example or story the audience probably hasn't heard.",
    "Go on a quick tangent connecting this to a totally different field, then tie it back.",
    "Ask your co-host a pointed question about what they just said, then give your hot take.",
    "Bring up a counterintuitive fact or common misconception and why people get it wrong.",
    "Make a bold prediction that would be controversial at a dinner party. Defend it.",
    "Bring in a pop culture reference or historical parallel that reframes the discussion.",
]

MAX_TRANSCRIPT_LINES = 24  # lines of context sent to the models each turn
WRAPUP_WINDOW_SECS = 150  # start wrapping up when this much episode time remains


def host_system_prompt(host: dict, other: dict) -> str:
    return (
        f"You are {host['name']}, co-host of the live call-in podcast '{SHOW_NAME}'.\n"
        f"Your personality: {host['personality']}\n"
        f"Your co-host is {other['name']} ({other['personality']}).\n"
        "Listeners can call in at any time; lines marked 'Caller' are live callers.\n\n"
        "Rules:\n"
        "- This is spoken audio. Plain conversational sentences only — never use "
        "emojis, bullet points, stage directions, or anything that can't be said aloud.\n"
        "- React to what was just said before adding your own point.\n"
        "- Keep each turn to 1-3 short sentences. Brevity keeps the show snappy.\n"
        "- Never prefix your line with your name or any label.\n"
        "- Never repeat what you or your co-host already said.\n"
        "- When a caller speaks, greet them briefly and engage with what they said."
    )


def inspire_prompt(category: str | None) -> str:
    cat_line = f' in the "{category}" category' if category and category != "all" else ""
    return (
        f"Generate exactly 4 creative, unexpected, and fun podcast topic ideas{cat_line}.\n"
        "Each should be a single sentence that sounds like an intriguing episode title.\n"
        "Make them diverse — mix serious and absurd.\n"
        "Return ONLY a JSON array of 4 strings, no other text.\n"
        'Example: ["Topic one", "Topic two", "Topic three", "Topic four"]'
    )


_THINK_RE = re.compile(r"<think>.*?(?:</think>|$)", re.DOTALL)
_LABEL_RE = re.compile(r"^\s*[A-Z][\w .'-]{0,24}:\s+")


def clean_line(text: str, host_names: tuple[str, ...]) -> str:
    """Make a model response speakable: drop reasoning, labels, and markdown."""
    text = _THINK_RE.sub("", text).strip()
    first = text.split(":", 1)[0].strip().strip("*_ ")
    if first in host_names and _LABEL_RE.match(text):
        text = text.split(":", 1)[1]
    text = text.replace("*", "").replace("#", "").replace("_", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


# --- session plumbing ------------------------------------------------------


class EventHub:
    """Fan-out of episode events (transcript lines, status) to SSE subscribers."""

    def __init__(self):
        self.history: list[dict] = []
        self._queues: set[asyncio.Queue] = set()

    def emit(self, event: dict):
        self.history.append(event)
        for q in self._queues:
            q.put_nowait(event)

    async def subscribe(self):
        q: asyncio.Queue = asyncio.Queue()
        self._queues.add(q)
        try:
            for event in self.history:
                yield event
            while True:
                yield await q.get()
        finally:
            self._queues.discard(q)


@dataclass
class Session:
    id: str
    topic: str
    hosts: dict  # {"a"/"b": {name, personality, model, voice, color}}
    duration_secs: int
    hub: EventHub = field(default_factory=EventHub)
    conductor: "PodcastConductor | None" = None
    created_at: float = field(default_factory=time.time)


SESSIONS: dict[str, Session] = {}


# --- pipeline processors ---------------------------------------------------


class ConversationTap(FrameProcessor):
    """Passive tap on the pipeline between STT and the TTS chain.

    Watches TranscriptionFrames (caller speech, downstream from Whisper) and
    BotStarted/StoppedSpeakingFrames (upstream from the output transport) and
    exposes them to the PodcastConductor as callbacks/events. All frames pass
    through untouched.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bot_speaking = False
        self.started_event = asyncio.Event()
        self.stopped_event = asyncio.Event()
        self.on_caller_text = None  # set by the conductor; async def (text, source) -> None

    def reset_speech_events(self):
        self.started_event.clear()
        self.stopped_event.clear()

    async def interrupt(self):
        """Clear any queued/playing host speech (caller barge-in)."""
        await self.queue_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, BotStartedSpeakingFrame):
            self.bot_speaking = True
            self.started_event.set()
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self.bot_speaking = False
            self.stopped_event.set()
        elif isinstance(frame, TranscriptionFrame) and not isinstance(
            frame, InterimTranscriptionFrame
        ):
            text = (frame.text or "").strip()
            if text and self.on_caller_text:
                await self.on_caller_text(text, source="voice")

        await self.push_frame(frame, direction)


# --- shared Kokoro TTS (one ONNX session per process, warmed once) ----------

_KOKORO: Kokoro | None = None
_KOKORO_LOCK = asyncio.Lock()


async def get_kokoro() -> Kokoro:
    global _KOKORO
    async with _KOKORO_LOCK:
        if _KOKORO is None:
            model = KOKORO_CACHE_DIR / "kokoro-v1.0.onnx"
            voices_bin = KOKORO_CACHE_DIR / "voices-v1.0.bin"
            await asyncio.to_thread(_ensure_model_files, model, voices_bin)
            kokoro = await asyncio.to_thread(Kokoro, str(model), str(voices_bin))
            # Warm the session: the first cold synthesis is several times slower.
            await asyncio.to_thread(kokoro.create, "Warm up.", voice="af_heart", lang="en-us")
            logger.info("Kokoro loaded and warmed")
            _KOKORO = kokoro
    return _KOKORO


# --- the show --------------------------------------------------------------


class PreparedTurn:
    """A generated line plus its in-flight synthesis stream."""

    def __init__(self, line: str):
        self.line = line
        self.queue: asyncio.Queue = asyncio.Queue()  # (pcm16, sample_rate) | None = EOS
        self.task: asyncio.Task | None = None

    def discard(self):
        if self.task and not self.task.done():
            self.task.cancel()


class PodcastConductor:
    """Turn loop: alternates host lines, folds in live callers, drives the TTSes."""

    def __init__(self, tap: ConversationTap, session: Session):
        self._tap = tap
        self._kokoro: Kokoro | None = None  # set in run()
        self._session = session
        self._hosts = session.hosts
        self._client = AsyncOpenAI(
            base_url=CRUSOE_API_BASE, api_key=os.environ["CRUSOE_API_KEY"]
        )
        self._transcript: list[dict] = []
        self._pending_callers: list[str] = []
        self._abort_speak = asyncio.Event()
        self._recent_host_words: deque[str] = deque(maxlen=150)
        self._host_names = tuple(h["name"] for h in self._hosts.values())
        tap.on_caller_text = self.on_caller_text
        session.conductor = self

    def _emit(self, kind: str, **data):
        self._session.hub.emit({"kind": kind, "t": time.time(), **data})

    # --- caller handling -------------------------------------------------

    def _looks_like_echo(self, text: str) -> bool:
        """Heuristic guard: without headphones, Whisper hears the hosts."""
        words = re.findall(r"[a-z']+", text.lower())
        if len(words) < 4:
            return False
        recent = set(self._recent_host_words)
        overlap = sum(1 for w in words if w in recent) / len(words)
        return overlap > 0.7

    async def on_caller_text(self, text: str, source: str = "voice"):
        text = text.strip()
        if len(text) < 3:
            return
        if source == "voice" and self._looks_like_echo(text):
            logger.debug(f"Ignoring probable host echo: [{text}]")
            return
        logger.info(f"Caller ({source}): [{text}]")
        self._pending_callers.append(text)
        self._transcript.append({"name": "Caller", "text": text})
        self._emit("line", speaker="caller", name="Caller", text=text, source=source)
        if self._tap.bot_speaking:
            self._abort_speak.set()
            await self._tap.interrupt()

    # --- generation ------------------------------------------------------

    def _render_transcript(self) -> str:
        lines = self._transcript[-MAX_TRANSCRIPT_LINES:]
        return "\n".join(f"{entry['name']}: {entry['text']}" for entry in lines)

    async def _generate(self, host_key: str, instruction: str) -> str:
        host = self._hosts[host_key]
        other = self._hosts["b" if host_key == "a" else "a"]
        script = self._render_transcript()
        user_msg = (
            (f"Transcript so far:\n{script}\n\n" if script else "")
            + f"Instruction for your next line: {instruction}"
        )
        messages = [
            {"role": "system", "content": host_system_prompt(host, other)},
            {"role": "user", "content": user_msg},
        ]
        kwargs = dict(model=host["model"], messages=messages, temperature=0.9, top_p=0.95,
                      max_tokens=2000)
        try:
            # Disabling thinking takes GLM/Nemotron lines from ~30s to ~1s.
            response = await self._client.chat.completions.create(
                **kwargs, extra_body={"chat_template_kwargs": {"enable_thinking": False}}
            )
        except Exception:
            response = await self._client.chat.completions.create(**kwargs)
        return clean_line(response.choices[0].message.content or "", self._host_names)

    def _instruction(self, turn: int) -> str:
        topic = self._session.topic
        if self._pending_callers:
            caller_text = " ".join(self._pending_callers)
            self._pending_callers.clear()
            return (
                f'A caller just said: "{caller_text}". Take the call: react to it, '
                "engage genuinely, and fold it into the show."
            )
        if turn == 0:
            return (
                f"Open the show: welcome listeners to '{SHOW_NAME}', introduce "
                f"yourself and your co-host, announce today's topic — {topic} — "
                "and remind listeners they can call in any time just by speaking. "
                "Energetic, 2 sentences max."
            )
        if turn >= 4 and turn % 5 == 0:
            return f"Topic: {topic}. {random.choice(VARIETY_PROMPTS)}"
        return (
            "Continue the conversation naturally: react to the last line, then add "
            f"your own take. Stay around the topic of {topic}; tangents welcome."
        )

    # --- speaking --------------------------------------------------------

    @staticmethod
    def _too_similar(a: str, b: str) -> bool:
        wa, wb = set(re.findall(r"[a-z']+", a.lower())), set(re.findall(r"[a-z']+", b.lower()))
        if not wa or not wb:
            return False
        return len(wa & wb) / len(wa | wb) > 0.6

    def _start_synth(self, host_key: str, line: str) -> "PreparedTurn":
        """Kick off sentence-by-sentence synthesis into a queue.

        Playback can begin as soon as the first sentence is ready instead of
        waiting for the whole line — crucial on CPU hardware where synthesis
        runs slower than realtime.
        """
        pt = PreparedTurn(line)
        voice = self._hosts[host_key]["voice"]
        sentences = [s for s in re.split(r"(?<=[.!?…])\s+", line) if s.strip()] or [line]

        async def produce():
            try:
                for sentence in sentences:
                    async for samples, sample_rate in self._kokoro.create_stream(
                        sentence, voice=voice, lang="en-us", speed=1.0
                    ):
                        pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes()
                        pt.queue.put_nowait((pcm, sample_rate))
            except Exception as e:
                logger.error(f"Synthesis failed: {e}")
            finally:
                pt.queue.put_nowait(None)

        pt.task = asyncio.create_task(produce())
        return pt

    async def _prepare(self, host_key: str, instruction: str) -> "PreparedTurn | None":
        """Generate a line and start synthesizing it. Runs in the background
        while the other host is still speaking so turn changes have no dead air."""
        line = await self._generate(host_key, instruction)
        recent = [e["text"] for e in self._transcript[-4:]]
        if line and any(self._too_similar(line, prev) for prev in recent):
            logger.warning(f"{self._hosts[host_key]['name']} repeated a recent line; regenerating")
            line = await self._generate(
                host_key,
                instruction + " IMPORTANT: do NOT repeat or rephrase anything already said "
                "in the transcript — contribute something genuinely new.",
            )
            if line and any(self._too_similar(line, prev) for prev in recent):
                logger.warning("Still repetitive; dropping the line to keep the show moving")
                line = ""
        if not line:
            return None
        return self._start_synth(host_key, line)

    async def _prepare_safe(self, host_key: str, instruction: str) -> "PreparedTurn | None":
        host = self._hosts[host_key]
        try:
            return await self._prepare(host_key, instruction)
        except Exception as e:
            logger.error(f"Turn preparation failed for {host['name']}: {e}")
            self._emit("error", message=f"{host['name']}'s turn failed; retrying.")
            await asyncio.sleep(3)
            return None

    def _record(self, host_key: str, line: str):
        host = self._hosts[host_key]
        logger.info(f"{host['name']}: [{line}]")
        self._transcript.append({"name": host["name"], "text": line})
        self._recent_host_words.extend(re.findall(r"[a-z']+", line.lower()))

    async def _race_abort(self, awaitable, timeout: float | None) -> str:
        """Await something, but bail instantly on caller barge-in.

        Returns "ok", "abort", or "timeout". Without this, a barge-in that
        clears not-yet-played audio would leave us waiting a full timeout for
        speech signals that can never arrive.
        """
        waiter = asyncio.ensure_future(awaitable)
        aborter = asyncio.create_task(self._abort_speak.wait())
        done, pending = await asyncio.wait(
            {waiter, aborter}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
        )
        for t in pending:
            t.cancel()
        if aborter in done:
            return "abort"
        return "ok" if waiter in done else "timeout"

    async def _speak(self, host_key: str, pt: "PreparedTurn"):
        """Stream synthesized PCM into the pipeline as it becomes available.

        The transcript "line" event is emitted only once audio actually starts
        playing (BotStartedSpeakingFrame reaching the tap), so text and voice
        stay in sync in the UI. If speech signals never arrive (transport
        quirk), fall back to an estimate of the spoken duration. A caller
        barge-in aborts every wait immediately.
        """
        words = max(1, len(pt.line.split()))
        estimate = words / 2.5 + 2
        line_event = dict(speaker=host_key, name=self._hosts[host_key]["name"], text=pt.line)
        self._abort_speak.clear()
        self._tap.reset_speech_events()

        try:
            while True:
                get_task = asyncio.create_task(pt.queue.get())
                if await self._race_abort(get_task, timeout=None) == "abort":
                    pt.discard()
                    return
                item = get_task.result()
                if item is None:
                    break
                pcm, sample_rate = item
                step = int(sample_rate * 2 * 0.02)  # 20 ms frames; output transport paces
                for i in range(0, len(pcm), step):
                    # SpeechOutputAudioRawFrame (not plain OutputAudioRawFrame):
                    # the output transport only tracks bot-speaking — and thus
                    # emits BotStarted/StoppedSpeakingFrame — for speech frames.
                    await self._tap.queue_frame(
                        SpeechOutputAudioRawFrame(
                            audio=pcm[i : i + step], sample_rate=sample_rate, num_channels=1
                        ),
                        FrameDirection.DOWNSTREAM,
                    )
                if self._tap.started_event.is_set() and not self._abort_speak.is_set():
                    # Audio is audibly playing: sync the transcript line now.
                    if not getattr(pt, "emitted", False):
                        pt.emitted = True
                        self._emit("line", **line_event)
                        self._emit("speaking", host=host_key)

            outcome = await self._race_abort(self._tap.started_event.wait(), timeout=40)
            if outcome == "abort":
                return
            if not getattr(pt, "emitted", False):
                if outcome == "timeout":
                    logger.warning("BotStartedSpeakingFrame never reached the tap; timing fallback")
                self._emit("line", **line_event)
                self._emit("speaking", host=host_key)
            if outcome == "ok":
                # All audio is queued now, so playback runs gap-free from here.
                # Discard any premature "stopped" caused by mid-line buffer
                # starvation (synthesis slower than realtime) and wait for the
                # true end of playback.
                self._tap.stopped_event.clear()
                await self._race_abort(self._tap.stopped_event.wait(), timeout=estimate * 2 + 20)
            else:
                await self._race_abort(asyncio.sleep(estimate), timeout=None)
        finally:
            self._emit("speaking", host=None)

    async def _take_turn(self, host_key: str, instruction: str) -> bool:
        pt = await self._prepare_safe(host_key, instruction)
        if not pt:
            return False
        self._record(host_key, pt.line)
        await self._speak(host_key, pt)
        await asyncio.sleep(0.3)  # small beat between turns
        return True

    # --- main loop -------------------------------------------------------

    async def run(self):
        session = self._session
        logger.info(
            f"Episode starting — topic: {session.topic}; "
            f"hosts: { {k: (h['name'], h['model'], h['voice']) for k, h in self._hosts.items()} }; "
            f"duration: {session.duration_secs}s"
        )
        self._emit("status", state="preparing")
        self._kokoro = await get_kokoro()

        started = time.time()
        deadline = started + session.duration_secs
        self._emit(
            "status",
            state="live",
            started_at=started,
            duration_secs=session.duration_secs,
            topic=session.topic,
            show=SHOW_NAME,
            hosts={
                k: {"name": h["name"], "color": h["color"], "model": h["model"], "voice": h["voice"]}
                for k, h in self._hosts.items()
            },
        )

        turn = 0
        current = "a"
        # While one host speaks, the next host's turn is generated AND
        # synthesized in the background so turn changes have no dead air.
        # A caller arriving mid-speech invalidates the prepared turn: the
        # show responds to the caller instead.
        prep: asyncio.Task | None = None
        prep_key: str | None = None

        def discard_prep():
            nonlocal prep, prep_key
            if prep:
                if prep.done():
                    pt = prep.exception() is None and prep.result()
                    if pt:
                        pt.discard()
                else:
                    prep.cancel()
            prep, prep_key = None, None

        try:
            while time.time() < deadline - WRAPUP_WINDOW_SECS:
                other = "b" if current == "a" else "a"
                if self._pending_callers:
                    discard_prep()
                    pt = await self._prepare_safe(current, self._instruction(turn))
                elif prep and prep_key == current:
                    try:
                        pt = await prep
                    except Exception as e:
                        logger.warning(f"Prepared turn failed ({e}); regenerating")
                        pt = await self._prepare_safe(current, self._instruction(turn))
                    prep, prep_key = None, None
                else:
                    discard_prep()
                    pt = await self._prepare_safe(current, self._instruction(turn))

                if not pt:
                    current = other
                    continue

                # Record before preparing the next turn so the next host sees
                # this line in the transcript.
                self._record(current, pt.line)
                turn += 1
                if not self._pending_callers:
                    prep = asyncio.create_task(self._prepare(other, self._instruction(turn)))
                    prep_key = other

                await self._speak(current, pt)
                await asyncio.sleep(0.3)
                current = other

            discard_prep()

            # Wrap-up: each host gives a closing thought, current host first.
            self._emit("status", state="wrapping_up")
            for i, key in enumerate([current, "b" if current == "a" else "a"]):
                closing = (
                    f"Time to wrap up the episode about {session.topic}. "
                    + (
                        "Give your final takeaway or hot take in 2-3 sentences."
                        if i == 0
                        else "Give your final thought, thank the callers and listeners, "
                        "and sign off the show warmly. 2-3 sentences."
                    )
                )
                await self._take_turn(key, closing)
        except asyncio.CancelledError:
            logger.info("Episode cancelled (client disconnected)")
            raise
        finally:
            if not asyncio.current_task().cancelled():
                self._emit("status", state="ended")
        logger.info("Episode ended")


# --- crusoe model catalog ---------------------------------------------------

_MODELS_CACHE: list[str] = []


async def get_crusoe_models() -> list[str]:
    global _MODELS_CACHE
    if _MODELS_CACHE:
        return _MODELS_CACHE
    client = AsyncOpenAI(base_url=CRUSOE_API_BASE, api_key=os.environ["CRUSOE_API_KEY"])
    models = [m.id async for m in client.models.list()]
    _MODELS_CACHE = sorted(m for m in models if not m.startswith("test-"))
    return _MODELS_CACHE


def default_model(host_key: str, available: list[str]) -> str:
    host = HOST_DEFAULTS[host_key]
    if host["model"] in available:
        return host["model"]
    for needle in host["model_needles"]:
        for m in available:
            if needle in m.lower():
                return m
    return available[0] if available else host["model"]


# --- per-connection pipeline ------------------------------------------------


async def run_bot(transport: BaseTransport, runner_args: WebSocketRunnerArguments, session: Session):
    logger.info(f"Starting pipeline for session {session.id}")

    whisper_model = os.environ.get("WHISPER_MODEL")
    stt = WhisperSTTService(
        settings=WhisperSTTService.Settings(model=whisper_model) if whisper_model else None,
    )

    vad = VADProcessor(vad_analyzer=SileroVADAnalyzer())

    tap = ConversationTap()

    # The conductor synthesizes each host's audio itself (one shared Kokoro
    # session, per-host voices) and streams raw audio frames in via the tap,
    # so the pipeline carries no TTS services at all.
    conductor = PodcastConductor(tap, session)

    pipeline = Pipeline(
        [
            transport.input(),
            vad,
            stt,
            tap,
            transport.output(),
        ]
    )

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
    )

    conductor_task: asyncio.Task | None = None

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        nonlocal conductor_task
        logger.info(f"Client connected (session {session.id})")
        if conductor_task is None or conductor_task.done():
            conductor_task = asyncio.create_task(conductor.run())

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info(f"Client disconnected (session {session.id})")
        if conductor_task and not conductor_task.done():
            conductor_task.cancel()
        await worker.cancel()

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    try:
        await runner.run()
    finally:
        if conductor_task and not conductor_task.done():
            conductor_task.cancel()
        SESSIONS.pop(session.id, None)


# --- web app -----------------------------------------------------------------

app = FastAPI(title="Call-In Podcast")


@app.on_event("startup")
async def _prewarm():
    """Load/warm Kokoro and the model catalog at boot, not on first episode."""

    async def warm():
        try:
            await get_kokoro()
        except Exception as e:
            logger.warning(f"Kokoro prewarm failed: {e}")
        try:
            await get_crusoe_models()
        except Exception as e:
            logger.warning(f"Model catalog prewarm failed: {e}")

    asyncio.create_task(warm())

transport_params = {
    # Plain WebSocket transport: audio rides the HTTPS connection, so this
    # works behind proxies that block UDP (e.g. Hugging Face Spaces). The
    # browser client speaks protobuf frames; without a serializer the
    # transport silently drops every frame in both directions.
    "websocket": lambda: FastAPIWebsocketParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        serializer=ProtobufFrameSerializer(),
    ),
}


@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/models")
async def api_models():
    try:
        models = await get_crusoe_models()
    except Exception as e:
        logger.error(f"Could not list Crusoe models: {e}")
        raise HTTPException(502, f"Could not reach Crusoe Managed Inference: {e}")
    return {
        "models": models,
        "voices": [{"id": v, "label": l} for v, l in KOKORO_VOICES.items()],
        "categories": INSPIRE_CATEGORIES,
        "hosts": {
            k: {
                "name": h["name"],
                "color": h["color"],
                "personality": h["personality"],
                "model": default_model(k, models),
                "voice": h["voice"],
            }
            for k, h in HOST_DEFAULTS.items()
        },
        "show": SHOW_NAME,
    }


@app.post("/api/inspire")
async def api_inspire(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    category = body.get("category") or "all"
    try:
        models = await get_crusoe_models()
        client = AsyncOpenAI(base_url=CRUSOE_API_BASE, api_key=os.environ["CRUSOE_API_KEY"])
        response = await client.chat.completions.create(
            model=default_model("b", models),
            messages=[{"role": "user", "content": inspire_prompt(category)}],
            temperature=1.2,
            top_p=0.95,
            max_tokens=2000,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        raw = _THINK_RE.sub("", response.choices[0].message.content or "").strip()
        # Models decorate the array differently (fences, lead-in text); grab
        # the first [...] block rather than assuming a format.
        match = re.search(r"\[.*?\]", raw, re.DOTALL)
        ideas = json.loads(match.group(0) if match else raw)
        assert isinstance(ideas, list) and ideas
        return {"ideas": [str(i) for i in ideas[:4]]}
    except Exception as e:
        logger.warning(f"Inspire failed ({e}); using fallback ideas")
        return {"ideas": random.sample(FALLBACK_TOPICS, 4)}


def _ws_url(request: Request, session_id: str) -> str:
    space_host = os.environ.get("SPACE_HOST")
    if space_host:
        return f"wss://{space_host}/ws?session={session_id}"
    host = request.headers.get("host", "localhost:7860")
    scheme = "wss" if request.url.scheme == "https" else "ws"
    return f"{scheme}://{host}/ws?session={session_id}"


@app.post("/start")
async def start(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    topic = (body.get("topic") or "").strip() or random.choice(FALLBACK_TOPICS)
    duration_mins = min(max(int(body.get("durationMinutes") or 30), 5), 120)

    try:
        available = await get_crusoe_models()
    except Exception:
        available = []

    hosts = {}
    for key, defaults in HOST_DEFAULTS.items():
        cfg = body.get("hosts", {}).get(key, {}) if isinstance(body.get("hosts"), dict) else {}
        model = cfg.get("model")
        if not model or (available and model not in available):
            model = default_model(key, available)
        voice = cfg.get("voice")
        if voice not in KOKORO_VOICES:
            voice = defaults["voice"]
        hosts[key] = {
            "name": (cfg.get("name") or "").strip()[:24] or defaults["name"],
            "personality": (cfg.get("personality") or "").strip()[:400] or defaults["personality"],
            "model": model,
            "voice": voice,
            "color": defaults["color"],
        }

    session = Session(
        id=str(uuid.uuid4()),
        topic=topic,
        hosts=hosts,
        duration_secs=duration_mins * 60,
    )
    SESSIONS[session.id] = session
    logger.info(
        f"Session {session.id}: topic={topic!r} mins={duration_mins} "
        f"hosts={ {k: (h['name'], h['model'], h['voice']) for k, h in hosts.items()} }"
    )
    return {"wsUrl": _ws_url(request, session.id), "sessionId": session.id}


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    session_id = websocket.query_params.get("session", "")
    session = SESSIONS.get(session_id)
    if session is None:
        await websocket.close(code=4004)
        return
    await websocket.accept()
    runner_args = WebSocketRunnerArguments(
        websocket=websocket, transport_type="websocket", session_id=session_id
    )
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args, session)


@app.post("/api/callin")
async def api_callin(request: Request):
    body = await request.json()
    session = SESSIONS.get(body.get("sessionId", ""))
    if session is None or session.conductor is None:
        raise HTTPException(404, "No live episode for that session")
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "Empty message")
    await session.conductor.on_caller_text(text[:500], source="text")
    return {"ok": True}


@app.get("/api/events")
async def api_events(session: str):
    sess = SESSIONS.get(session)
    if sess is None:
        raise HTTPException(404, "Unknown session")

    async def stream():
        try:
            async for event in sess.hub.subscribe():
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("kind") == "status" and event.get("state") == "ended":
                    break
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    if not os.environ.get("CRUSOE_API_KEY"):
        raise SystemExit(
            "CRUSOE_API_KEY is not set. Add it to .env (local) or as a Space secret."
        )
    port = int(os.environ.get("PORT", "7860"))
    uvicorn.run(app, host="0.0.0.0", port=port)
