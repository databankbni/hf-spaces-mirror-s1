"""Capture audio from the microphone as a 16 kHz mono float32 array."""
import sys

import numpy as np

SAMPLE_RATE = 16000


def record_fixed(seconds: float = 6.0) -> np.ndarray:
    """Record for a fixed number of seconds."""
    import sounddevice as sd

    print(f"\n🎙  Recording for {seconds:.0f}s — recite the verse now...")
    audio = sd.rec(
        int(seconds * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
    )
    sd.wait()
    print("✓ Done recording.")
    return audio.flatten()


def record_until_enter() -> np.ndarray:
    """Record from mic until the user presses Enter (push-to-stop)."""
    import sounddevice as sd

    frames = []

    def callback(indata, frames_count, time_info, status):
        if status:
            print(status, file=sys.stderr)
        frames.append(indata.copy())

    print("\n🎙  Recording... speak the verse, then press Enter to stop.")
    with sd.InputStream(
        samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=callback
    ):
        input()
    print("✓ Done recording.")

    if not frames:
        return np.zeros(0, dtype="float32")
    return np.concatenate(frames, axis=0).flatten()


if __name__ == "__main__":
    a = record_until_enter()
    print(f"Captured {len(a)} samples ({len(a) / SAMPLE_RATE:.1f}s)")
