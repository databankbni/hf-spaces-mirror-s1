# ---------------------------------------------------------------------------
# agent/build_agent.py
#
# "Ask the Sage" chat. Llama-3.1-8B (and its providers) do NOT support
# function/tool calling, so instead of a ToolCallingAgent we do plain
# Retrieval-Augmented Generation:
#
#   1. If the question names a specific verse ("chapter 2 verse 47"),
#      look it up directly in SQLite.
#   2. Otherwise semantically search the Chroma index for the top verses.
#   3. Feed those verses to the model and ask it to answer AS A SAGE,
#      grounded only in those verses, citing [BGx.y] references.
#
# This is cheaper and far more reliable than tool-calling, and the LLM is
# still the ONLY place a model is used — the reading loop never calls it.
# ---------------------------------------------------------------------------

import os
import re

from huggingface_hub import InferenceClient

from config import CHAT_MODEL_ID, ROOT
from agent.retriever import VerseRetriever
from reader.verse_store import VerseStore

REFUSAL_PHRASE = "I don't know based on the Bhagavad Gita verses available."

# The sage persona — warm, wise, addressing the seeker directly.
SYSTEM_PROMPT = (
    "You are a serene, wise sage well-versed in the Bhagavad Gita, speaking "
    "gently to a seeker. Explain the meaning of the provided verses as a "
    "spiritual teacher would: address the seeker warmly (e.g. 'Dear seeker'), "
    "draw out the deeper teaching in plain, compassionate language, and stay "
    "faithful to the verses given.\n\n"
    "RULES:\n"
    "- Ground every point ONLY in the context verses provided. Do not invent "
    "verses, names, or numbers.\n"
    "- Cite the verses you draw upon like [BG2.47].\n"
    "- Keep it concise (a short paragraph), reflective, and encouraging.\n"
    f"- If the verses do not address the question, reply exactly: {REFUSAL_PHRASE}"
)

# Appended when the seeker is reading in Hindi, so the sage replies in Hindi.
HINDI_INSTRUCTION = (
    "\n- Respond entirely in Hindi (Devanagari script), warmly addressing the "
    "seeker (e.g. 'प्रिय साधक'). Keep the [BGx.y] citations in their original "
    "form."
)
HINDI_REFUSAL_PHRASE = "उपलब्ध भगवद्गीता के श्लोकों के आधार पर मुझे यह ज्ञात नहीं है।"

# Kept so app.py's import keeps working; the question passes through unchanged
# because the sage persona is applied inside GitaSage.
GROUNDED_PREAMBLE = "{question}"

_VERSE_REF_RE = re.compile(
    r"chapter\s+(\d+)\s*(?:,|\s|verse|shloka|sloka)+\s*(\d+)", re.IGNORECASE
)
_SHORT_REF_RE = re.compile(r"\bBG\s*(\d+)[.\s:](\d+)\b", re.IGNORECASE)


def _read_token() -> str:
    """Resolve the HF token, preferring whatever the *current* environment
    provides.

    On a Hugging Face Space (detected via the auto-set SPACE_ID) we read the
    token Hugging Face injects — the HF_TOKEN secret, or the hub's own cached
    token via huggingface_hub.get_token() — so nothing depends on a file.

    Locally we prefer AccessToken.txt next to the repo (the developer's
    known-good token), then fall back to the environment."""
    on_space = bool(os.environ.get("SPACE_ID"))
    fallback = ROOT.parent / "AccessToken.txt"

    def _from_env() -> str | None:
        tok = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
        if tok and tok.strip():
            return tok.strip()
        try:
            from huggingface_hub import get_token

            tok = get_token()
        except Exception:  # noqa: BLE001
            tok = None
        return tok.strip() if tok else None

    def _from_file() -> str | None:
        if fallback.exists():
            tok = fallback.read_text(encoding="utf-8").strip()
            if tok:
                return tok
        return None

    token = _from_env() if on_space else (_from_file() or _from_env())
    if token:
        return token

    raise RuntimeError(
        "No HF token found. On a Space, add the HF_TOKEN secret (Settings → "
        "Variables and secrets). For local dev, place a token in "
        "AccessToken.txt next to the repo."
    )


def _parse_verse_ref(text: str) -> tuple[int, int] | None:
    """Extract a (chapter, verse) reference from free text, if present."""
    m = _VERSE_REF_RE.search(text) or _SHORT_REF_RE.search(text)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


class GitaSage:
    """RAG chat over the Gita, answering in a sage's voice. `jump_sink` is a
    shared dict the UI reads to apply a 'jump to this verse' request."""

    def __init__(self, store: VerseStore, jump_sink: dict):
        self.store = store
        self.jump_sink = jump_sink
        self.retriever = VerseRetriever()
        self.client = InferenceClient(provider="auto", api_key=_read_token())

    def _context_from_lookup(self, chapter: int, verse: int) -> tuple[str, str | None]:
        v = self.store.get_by_chapter_verse(chapter, verse)
        if v is None:
            return "", None
        block = f"[{v.verse_id}] (Sanskrit) {v.sanskrit}\n(English) {v.english}"
        return block, v.verse_id

    def _context_from_search(self, question: str, k: int = 4) -> tuple[str, str | None]:
        hits = self.retriever.query(question, k=k)
        if not hits:
            return "", None
        blocks = [f"[{h['verse_id']}] {h['text']}" for h in hits]
        return "\n\n".join(blocks), hits[0]["verse_id"]

    def _context_up_to(
        self, question: str, up_to_verse_id: str, k: int = 4
    ) -> tuple[str, str | None]:
        """Semantic search restricted to verses the seeker has heard so far
        (from the start of the book up to `up_to_verse_id`)."""
        allowed = self.store.verse_ids_up_to(up_to_verse_id)
        hits = self.retriever.query(question, k=k, allowed_ids=allowed)
        if not hits:
            return "", None
        blocks = [f"[{h['verse_id']}] {h['text']}" for h in hits]
        return "\n\n".join(blocks), hits[0]["verse_id"]

    def answer(
        self, question: str, lang: str = "en", up_to_verse_id: str | None = None
    ) -> str:
        question = (question or "").strip()
        if not question:
            return "Please type a question."

        hindi = str(lang).lower().startswith("hi")
        refusal = HINDI_REFUSAL_PHRASE if hindi else REFUSAL_PHRASE

        ref = _parse_verse_ref(question)
        if ref is not None:
            context, top_id = self._context_from_lookup(*ref)
            if not context:
                if hindi:
                    return f"मुझे अध्याय {ref[0]} श्लोक {ref[1]} नहीं मिला।"
                return f"I couldn't find chapter {ref[0]} verse {ref[1]}."
        elif up_to_verse_id:
            # Ground the sage in only what the seeker has heard so far.
            context, top_id = self._context_up_to(question, up_to_verse_id)
            if not context:
                if hindi:
                    return (
                        "आपने अभी तक जो श्लोक सुने हैं, उनके आधार पर मुझे इसका "
                        "उत्तर नहीं मिलता।"
                    )
                return (
                    "Based on the verses you've heard so far, I don't find an "
                    "answer to that."
                )
        else:
            context, top_id = self._context_from_search(question)
            if not context:
                return refusal

        # If the seeker asked to jump/go to a verse, record it for the UI.
        if top_id and re.search(
            r"\b(jump|go to|take me|start (?:at|from))\b", question, re.IGNORECASE
        ):
            self.jump_sink["verse_id"] = top_id

        system_prompt = SYSTEM_PROMPT + (HINDI_INSTRUCTION if hindi else "")
        if hindi:
            instruction = (
                "एक संत के रूप में, केवल ऊपर दिए गए श्लोकों के आधार पर "
                "उत्तर दें और [BGx.y] उद्धरण दें।"
            )
        else:
            instruction = (
                "As the sage, explain using only the context verses above, "
                "citing [BGx.y]."
            )
        user_msg = (
            f"Context verses:\n{context}\n\n"
            f"The seeker asks: {question}\n\n"
            f"{instruction}"
        )
        resp = self.client.chat_completion(
            model=CHAT_MODEL_ID,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.3,
            max_tokens=400,
        )
        return resp.choices[0].message.content.strip()

    def reflect(self, verse_id: str, lang: str = "en") -> str:
        """Generate the sage's short reflection on a SINGLE verse, used by the
        reading view. No retrieval — the verse itself is the only context, so
        the commentary stays faithful to what the seeker is reading."""
        v = self.store.get_verse(verse_id)
        if v is None:
            return ""
        hindi = str(lang).lower().startswith("hi")

        context = (
            f"[{v.verse_id}] (Sanskrit) {v.sanskrit}\n(English) {v.english}"
        )
        system_prompt = SYSTEM_PROMPT + (HINDI_INSTRUCTION if hindi else "")
        if hindi:
            instruction = (
                "एक संत के रूप में, इस श्लोक का गूढ़ अर्थ और इसकी शिक्षा को "
                "२-३ वाक्यों में, केवल इसी श्लोक के आधार पर समझाएँ। "
                f"उद्धरण [{v.verse_id}] दें।"
            )
        else:
            instruction = (
                "As the sage, explain the deeper teaching of THIS verse in "
                "2-3 sentences, grounded only in this verse. "
                f"Cite [{v.verse_id}]."
            )
        user_msg = f"Verse:\n{context}\n\n{instruction}"
        resp = self.client.chat_completion(
            model=CHAT_MODEL_ID,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.3,
            max_tokens=220,
        )
        return resp.choices[0].message.content.strip()

    # Compatibility shim so existing app.py code calling `.run()` keeps working.
    def run(
        self, question: str, lang: str = "en", up_to_verse_id: str | None = None
    ) -> str:
        return self.answer(question, lang, up_to_verse_id)


def build_agent(store: VerseStore, jump_sink: dict) -> GitaSage:
    """Construct the RAG sage for the 'Ask the Sage' panel."""
    print(f"[agent] connecting to HF Inference Providers for {CHAT_MODEL_ID}...")
    return GitaSage(store, jump_sink)
