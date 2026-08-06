# ---------------------------------------------------------------------------
# ingestion/build_bgm.py
#
# Synthesizes a soft, looping "temple" ambience to play quietly behind the
# Gita recitation. Two layers, generated from scratch with numpy (so there
# are no copyright concerns):
#
#   1. A sustained tanpura-style drone (Sa + Pa + upper Sa) with a slow
#      shimmer, giving the warm, meditative pad of a mandir.
#   2. A slow bansuri-style flute melody in Raga Bhupali (the serene,
#      devotional pentatonic Sa Re Ga Pa Dha), with gentle vibrato and a
#      soft echo so it feels spacious and mythological.
#
# The whole cycle is crossfaded onto itself so it loops seamlessly. Written
# to data/audio_cache/bgm.wav; ensure_bgm() rebuilds it when the stored
# version is out of date.
# ---------------------------------------------------------------------------

import wave

import numpy as np

from config import AUDIO_DIR

BGM_PATH = AUDIO_DIR / "bgm.wav"

# Bump this whenever the sound design changes so ensure_bgm() rebuilds the
# cached wav (and a fresh one gets deployed).
_BGM_VERSION = 2

_SAMPLE_RATE = 22050

# --- Raga Bhupali (relative to Sa = D3), a calm, devotional pentatonic. ---
_SA = 146.83          # D3 (drone root)
_PA_DRONE = 220.00    # A3 (the fifth, the tanpura's companion string)
_SA_OCT = 293.66      # D4 (upper Sa, sweetens the drone)

# Bansuri melody notes (one octave up from the root), Hz.
_RE = 329.63   # E4
_GA = 369.99   # F#4
_PA = 440.00   # A4
_DHA = 493.88  # B4
_SA_HI = 587.33  # D5


def _adsr(n: int, sr: int, attack: float, release: float) -> np.ndarray:
    """A soft attack/release envelope for one flute note (sustain at 1.0)."""
    env = np.ones(n)
    a = min(max(1, int(attack * sr)), n)
    r = min(max(1, int(release * sr)), n - a) if n - a > 0 else 0
    env[:a] = np.linspace(0.0, 1.0, a)
    if r:
        env[-r:] = np.linspace(1.0, 0.0, r)
    return env


def _flute(freq: float, seconds: float, sr: int) -> np.ndarray:
    """A bansuri-like tone: a breathy sine with a couple of soft harmonics
    and a gentle vibrato."""
    n = int(seconds * sr)
    t = np.arange(n) / sr
    vibrato = 1.0 + 0.006 * np.sin(2 * np.pi * 5.0 * t)  # ~5 Hz, subtle
    phase = 2 * np.pi * freq * t * vibrato
    tone = (
        1.0 * np.sin(phase)
        + 0.25 * np.sin(2 * phase)
        + 0.08 * np.sin(3 * phase)
    )
    # A whisper of breath noise shaped by the note envelope.
    breath = 0.015 * np.random.randn(n)
    env = _adsr(n, sr, attack=0.12, release=0.35)
    return (tone + breath) * env


def _drone(seconds: float, sr: int) -> np.ndarray:
    """A continuous, sustained tanpura-style pad: Sa + Pa + upper Sa with a
    slow tremolo shimmer."""
    n = int(seconds * sr)
    t = np.arange(n) / sr
    shimmer = 1.0 + 0.05 * np.sin(2 * np.pi * 0.15 * t)  # slow breathing
    pad = np.zeros(n)
    for freq, amp in ((_SA, 0.6), (_PA_DRONE, 0.4), (_SA_OCT, 0.25)):
        ph = 2 * np.pi * freq * t
        pad += amp * (np.sin(ph) + 0.3 * np.sin(2 * ph) + 0.12 * np.sin(3 * ph))
    return pad * shimmer


def _echo(sig: np.ndarray, sr: int, delay: float = 0.33, decay: float = 0.35,
          taps: int = 3) -> np.ndarray:
    """A simple feedback delay so the flute feels spacious, like a temple."""
    out = sig.copy()
    d = int(delay * sr)
    for k in range(1, taps + 1):
        shift = d * k
        if shift >= len(sig):
            break
        out[shift:] += (decay ** k) * sig[: len(sig) - shift]
    return out


def build_bgm() -> None:
    """Generate a ~40s seamless temple ambience and write it as 16-bit WAV."""
    sr = _SAMPLE_RATE
    total_seconds = 40.0
    np.random.seed(108)  # deterministic output

    # --- Layer 1: the sustained drone underneath everything. ---
    drone = _drone(total_seconds, sr)

    # --- Layer 2: a slow Bhupali flute phrase, with rests for stillness. ---
    beat = 1.1  # seconds per beat
    phrase = [
        (_SA_OCT, 2), (_RE, 1), (_GA, 2), (None, 1),
        (_PA, 2), (_GA, 1), (_RE, 1), (_SA_OCT, 2), (None, 1),
        (_GA, 1), (_PA, 1), (_DHA, 2), (_SA_HI, 2), (None, 1),
        (_DHA, 1), (_PA, 1), (_GA, 2), (_RE, 1), (_SA_OCT, 2), (None, 1),
    ]
    melody_parts: list[np.ndarray] = []
    for note, beats in phrase:
        seconds = beats * beat
        if note is None:
            melody_parts.append(np.zeros(int(seconds * sr)))
        else:
            melody_parts.append(_flute(note, seconds, sr))
    melody = np.concatenate(melody_parts)

    # Fit the melody to the drone length (pad or trim), then add echo.
    if len(melody) < len(drone):
        melody = np.concatenate([melody, np.zeros(len(drone) - len(melody))])
    else:
        melody = melody[: len(drone)]
    melody = _echo(melody, sr)

    # --- Mix: drone quiet and warm, flute a touch louder but still gentle. ---
    mix = 0.5 * drone + 0.85 * melody

    # --- Seamless loop: crossfade the tail into the head. ---
    xf = int(1.0 * sr)
    if len(mix) > 2 * xf:
        head = mix[:xf].copy()
        tail = mix[-xf:].copy()
        fade = np.linspace(0.0, 1.0, xf)
        mix[:xf] = head * fade + tail * (1.0 - fade)
        mix = mix[:-xf]

    # Normalize to a gentle level (the <audio> element also lowers volume).
    peak = float(np.max(np.abs(mix))) or 1.0
    mix = (mix / peak) * 0.7

    BGM_PATH.parent.mkdir(parents=True, exist_ok=True)
    pcm16 = (np.clip(mix, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(BGM_PATH), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm16.tobytes())
    _write_version()
    print(f"[build_bgm] wrote {BGM_PATH} ({len(mix) / sr:.1f}s, v{_BGM_VERSION})")


def _version_path():
    return BGM_PATH.with_suffix(".version")


def _write_version() -> None:
    _version_path().write_text(str(_BGM_VERSION), encoding="utf-8")


def _current_version() -> int:
    p = _version_path()
    if not p.exists():
        return 0
    try:
        return int(p.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return 0


def ensure_bgm() -> None:
    """Generate the temple ambience if it's missing or out of date."""
    if BGM_PATH.exists() and _current_version() >= _BGM_VERSION:
        print("[ensure_bgm] background music already present, skipping.")
        return
    build_bgm()


if __name__ == "__main__":
    build_bgm()
