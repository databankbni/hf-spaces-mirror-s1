"""
Forced alignment for Arabic read-aloud, constrained by the known text.

This is not recognition. We already know what the reader was asked to say, so the
job is to find where each character of that text landed in the audio. A CTC model
gives per-frame character probabilities; torchaudio's forced_align finds the most
likely monotonic path through them that spells the expected text and nothing else.

Because the path is constrained to the target, the model cannot invent a fluent
reading — which is exactly the failure mode that makes Whisper unusable here.

Per-character timings are the point. They make the three productions separable:

    fluent     one connected run; no long silence before or inside
    assembled  long silence, then the characters arrive close together
    spelled    silences BETWEEN the characters of a single word
"""

from __future__ import annotations

import re
import unicodedata as ud
from dataclasses import dataclass, asdict

import torch
import torchaudio
from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

MODEL_ID = "jonatasgrosman/wav2vec2-large-xlsr-53-arabic"
SR = 16_000

# tuning, in milliseconds
INNER_GAP = 120     # silence inside a word that counts as it coming apart
LEAD_GAP = 400      # silence before a word that counts as working it out first
SPELL_FRACTION = 0.5  # gaps affecting this share of a word's letters = spelled out

_MARKS = set("ًٌٍَُِّْٰ")
strip_marks = lambda s: "".join(c for c in s if c not in _MARKS)


@dataclass
class WordResult:
    word: str
    state: str          # fluent | hesitant | slow | assembled | broken | spelled | missing
    label: str
    start_ms: int
    end_ms: int
    lead_ms: int
    inner_gaps: int
    max_inner_gap_ms: int
    score: float        # mean alignment confidence, 0..1
    chars: list         # [[char, start_ms, end_ms], ...]


class Aligner:
    def __init__(self, model_id: str = MODEL_ID, device: str | None = None):
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.processor = Wav2Vec2Processor.from_pretrained(model_id)
        self.model = Wav2Vec2ForCTC.from_pretrained(model_id).to(self.device).eval()
        vocab = self.processor.tokenizer.get_vocab()
        self.vocab = {k: v for k, v in vocab.items()}
        self.blank = self.vocab.get("<pad>", 0)

    # ---------- text ----------
    def _tokens_for(self, words: list[str]):
        """Map the expected words to vocab ids, remembering which word each id came from."""
        ids, owner, chars = [], [], []
        for wi, w in enumerate(words):
            base = strip_marks(w)
            base = re.sub(r"[آأإٱ]", "ا", base)  # alef variants
            base = re.sub(r"ى", "ي", base)
            base = re.sub(r"ة", "ه", base)
            for ch in base:
                tid = self.vocab.get(ch)
                if tid is None:
                    continue
                ids.append(tid)
                owner.append(wi)
                chars.append(ch)
        return ids, owner, chars

    # ---------- audio ----------
    @staticmethod
    def load_audio(path: str) -> torch.Tensor:
        wav, sr = torchaudio.load(path)
        if wav.shape[0] > 1:
            wav = wav.mean(0, keepdim=True)
        if sr != SR:
            wav = torchaudio.functional.resample(wav, sr, SR)
        return wav.squeeze(0)

    # ---------- alignment ----------
    @torch.inference_mode()
    def align(self, wav: torch.Tensor, words: list[str]) -> dict:
        ids, owner, chars = self._tokens_for(words)
        if not ids:
            return {"error": "no alignable characters in the expected text"}

        inputs = self.processor(wav.numpy(), sampling_rate=SR, return_tensors="pt")
        logits = self.model(inputs.input_values.to(self.device)).logits
        log_probs = torch.log_softmax(logits, dim=-1).cpu()

        targets = torch.tensor([ids], dtype=torch.int32)
        try:
            paths, scores = torchaudio.functional.forced_align(
                log_probs, targets, blank=self.blank
            )
        except Exception as exc:                      # audio shorter than the text
            return {"error": f"alignment failed: {exc}"}

        spans = torchaudio.functional.merge_tokens(paths[0], scores[0].exp(), blank=self.blank)
        ms_per_frame = (wav.shape[-1] / SR) * 1000.0 / log_probs.shape[1]

        # spans come back in target order, one per emitted token
        per_char = []
        for i, sp in enumerate(spans):
            if i >= len(owner):
                break
            per_char.append({
                "wi": owner[i], "ch": chars[i],
                "s": sp.start * ms_per_frame, "e": sp.end * ms_per_frame,
                "score": float(sp.score),
            })
        return self._classify(words, per_char)

    # ---------- the pedagogy ----------
    def _classify(self, words: list[str], per_char: list[dict]) -> dict:
        by_word: dict[int, list[dict]] = {}
        for c in per_char:
            by_word.setdefault(c["wi"], []).append(c)

        results: list[WordResult] = []
        prev_end = 0.0
        for wi, w in enumerate(words):
            cs = by_word.get(wi)
            if not cs:
                results.append(WordResult(w, "missing", "not heard", 0, 0, 0, 0, 0, 0.0, []))
                continue
            cs.sort(key=lambda c: c["s"])
            start, end = cs[0]["s"], cs[-1]["e"]
            lead = start - prev_end
            prev_end = end

            gaps = [cs[i]["s"] - cs[i - 1]["e"] for i in range(1, len(cs))]
            inner = [g for g in gaps if g >= INNER_GAP]
            max_gap = max(inner) if inner else 0.0
            letters = max(len(cs), 1)
            score = sum(c["score"] for c in cs) / letters
            dur = end - start
            expected = 90.0 * letters          # provisional; caller may recalibrate

            if len(inner) >= max(2, letters * SPELL_FRACTION):
                state, label = "spelled", f"sounded out — {len(inner) + 1} separate pieces"
            elif inner:
                state, label = "broken", f"came apart — {int(max_gap)}ms silence inside the word"
            elif lead > LEAD_GAP:
                state, label = "assembled", f"{int(lead)}ms of silence, then said whole — worked out before speaking"
            elif dur > expected * 1.8:
                state, label = "slow", "laboured"
            elif dur > expected * 1.3:
                state, label = "hesitant", "slightly hesitant"
            else:
                state, label = "fluent", "read as one unit"

            results.append(WordResult(
                w, state, label, int(start), int(end), int(max(lead, 0)),
                len(inner), int(max_gap), round(score, 3),
                [[c["ch"], int(c["s"]), int(c["e"])] for c in cs],
            ))

        # second pass: recalibrate pace from the words that came out clean
        clean = [r for r in results if r.state in ("fluent", "hesitant")]
        if clean:
            per_letter = sum((r.end_ms - r.start_ms) for r in clean) / max(
                sum(len(r.chars) for r in clean), 1)
            for r in results:
                if r.state in ("fluent", "hesitant", "slow") and r.chars:
                    exp = per_letter * len(r.chars)
                    dur = r.end_ms - r.start_ms
                    if dur > exp * 1.8:
                        r.state, r.label = "slow", f"laboured — {int(100 * dur / max(exp, 1))}% of your own pace"
                    elif dur > exp * 1.3:
                        r.state, r.label = "hesitant", "slightly hesitant"
                    else:
                        r.state, r.label = "fluent", "read as one unit"

        tally = lambda s: sum(1 for r in results if r.state == s)
        return {
            "words": [asdict(r) for r in results],
            "summary": {
                "fluent": tally("fluent"),
                "assembled": tally("assembled"),
                "spelled": tally("spelled") + tally("broken"),
                "missing": tally("missing"),
                "mean_score": round(sum(r.score for r in results) / max(len(results), 1), 3),
            },
        }

    # ---------- constrained choice, for the flash drill ----------
    @torch.inference_mode()
    def best_of(self, wav: torch.Tensor, candidates: list[str]) -> dict:
        """Which of these known words was said? Align against each, take the best score.
        Far more robust than open recognition: we are choosing among four, not searching."""
        scored = []
        for c in candidates:
            out = self.align(wav, [c])
            if "error" in out:
                scored.append({"word": c, "score": 0.0})
                continue
            scored.append({"word": c, "score": out["summary"]["mean_score"]})
        scored.sort(key=lambda x: -x["score"])
        top, runner = scored[0], (scored[1] if len(scored) > 1 else {"score": 0.0})
        return {
            "best": top["word"],
            "score": top["score"],
            "margin": round(top["score"] - runner["score"], 3),
            "confident": top["score"] > 0.35 and (top["score"] - runner["score"]) > 0.08,
            "all": scored,
        }
