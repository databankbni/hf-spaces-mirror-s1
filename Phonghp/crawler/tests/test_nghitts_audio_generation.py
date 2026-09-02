import tempfile
import unittest
from pathlib import Path

import numpy as np

import video_generator


class NghiTTSChunkFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_audio_from_text_skips_failed_nghitts_chunks(self):
        class DummyEngine:
            def __init__(self):
                self.default_scales = np.array([0.0, 1.0, 0.0], dtype=np.float32)
                self.sample_rate = 22050

            def normalize_text(self, text):
                return text

            def generate_audio(self, text, scales=None):
                if "bad" in text:
                    raise RuntimeError("NghiTTS generated no audio from text")
                return np.array([0.1, 0.2, 0.3], dtype=np.float32)

            @staticmethod
            def audio_to_wav_bytes(audio_data, sample_rate):
                return b"wav-bytes"

        original_engine_cls = video_generator.NghiTTSEngine
        video_generator.NghiTTSEngine = lambda *_args, **_kwargs: DummyEngine()
        video_generator._split_nghitts_text_for_tts = lambda *args, **kwargs: ["good chunk", "bad chunk"]

        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                output_path = Path(tmp_dir) / "output.wav"
                await video_generator.create_audio_from_text(
                    "hello world",
                    output_path,
                    voice="nghitts:ngochuyennew",
                    rate="+0%",
                    job_id="job-1",
                )
                self.assertEqual(output_path.read_bytes(), b"wav-bytes")
        finally:
            video_generator.NghiTTSEngine = original_engine_cls
            video_generator._split_nghitts_text_for_tts = video_generator._split_nghitts_text_for_tts


if __name__ == "__main__":
    unittest.main()
