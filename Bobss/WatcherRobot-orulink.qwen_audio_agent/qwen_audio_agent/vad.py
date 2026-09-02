"""Small dependency-free PCM16 threshold VAD for the managed Application."""

from __future__ import annotations

import math
import sys
from array import array
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class VadDecision:
    """One threshold decision and the PCM frames that should be uploaded."""

    rms: int
    audio_frames: tuple[bytes, ...] = ()
    started: bool = False
    ended: bool = False
    forced: bool = False


class ThresholdVad:
    """Detect speech with consecutive RMS thresholds and hysteresis.

    The detector buffers a bounded pre-roll while idle.  It deliberately owns
    no device or network resources, so the bridge can close the ESP32 recorder
    before starting playback.
    """

    def __init__(
        self,
        *,
        start_rms: int,
        stop_rms: int,
        start_frames: int,
        silence_frames: int,
        pre_roll_frames: int,
        max_speech_frames: int,
    ) -> None:
        if start_rms <= 0:
            raise ValueError("start_rms must be positive")
        if stop_rms < 0 or stop_rms > start_rms:
            raise ValueError("stop_rms must be between 0 and start_rms")
        for name, value in (
            ("start_frames", start_frames),
            ("silence_frames", silence_frames),
            ("pre_roll_frames", pre_roll_frames),
            ("max_speech_frames", max_speech_frames),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        self._start_rms = start_rms
        self._stop_rms = stop_rms
        self._start_frames = start_frames
        self._silence_frames = silence_frames
        self._max_speech_frames = max_speech_frames
        self._pre_roll: deque[bytes] = deque(maxlen=pre_roll_frames)
        self._in_speech = False
        self._loud_frames = 0
        self._quiet_frames = 0
        self._speech_frames = 0

    @property
    def in_speech(self) -> bool:
        return self._in_speech

    def reset(self) -> None:
        self._pre_roll.clear()
        self._in_speech = False
        self._loud_frames = 0
        self._quiet_frames = 0
        self._speech_frames = 0

    def process(self, pcm: bytes) -> VadDecision:
        frame = bytes(pcm)
        rms = _pcm16_rms(frame)
        if not self._in_speech:
            self._pre_roll.append(frame)
            self._loud_frames = (
                self._loud_frames + 1 if rms >= self._start_rms else 0
            )
            if self._loud_frames < self._start_frames:
                return VadDecision(rms=rms)
            audio_frames = tuple(self._pre_roll)
            self._pre_roll.clear()
            self._in_speech = True
            self._loud_frames = 0
            self._quiet_frames = 0
            self._speech_frames = 1
            return VadDecision(
                rms=rms,
                audio_frames=audio_frames,
                started=True,
            )

        self._speech_frames += 1
        if rms <= self._stop_rms:
            self._quiet_frames += 1
        else:
            self._quiet_frames = 0
        forced = self._speech_frames >= self._max_speech_frames
        ended = forced or self._quiet_frames >= self._silence_frames
        decision = VadDecision(
            rms=rms,
            audio_frames=(frame,),
            ended=ended,
            forced=forced,
        )
        if ended:
            self.reset()
        return decision


def _pcm16_rms(pcm: bytes) -> int:
    if not pcm or len(pcm) % 2:
        raise ValueError("PCM16 frame must contain complete samples")
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    mean_square = sum(int(sample) * int(sample) for sample in samples) // len(samples)
    return math.isqrt(mean_square)
