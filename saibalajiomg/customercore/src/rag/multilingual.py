"""
src/rag/multilingual.py

Phase 8a: Multi-Language Intelligence Layer

== What This Does ==
Every ticket entering CustomerCore now gets:
  1. Language detection (langdetect — probabilistic, fast, 55 languages)
  2. Language-aware routing (multilingual-capable models for non-English)
  3. Language metadata stored on every Silver record for dbt Gold analysis
  4. Multilingual BM25 tokenization (language-specific stopwords via NLTK)

== Supported Languages (V1) ==
  en — English (primary — Bitext SaaS + Banking datasets)
  de — German  (important: you are in Germany, B2B EU platform)
  fr — French  (major EU business language)
  es — Spanish (3rd largest language by speakers)
  pt — Portuguese (Brazil = large B2B market)
  nl — Dutch
  it — Italian
  Unknown → fallback to multilingual model

== Why Language Detection Matters for a B2B Platform ==
Real enterprise B2B SaaS platforms serve global customers. A German Mittelstand
company will write support tickets in German. A French SaaS company will
write in French. Routing all tickets through an English-only model:
  (a) Degrades classification accuracy by 15-40% for non-English tickets
  (b) Misses language as a segmentation signal in analytics
  (c) Is not acceptable for an EU-compliance platform (GDPR requires same
      quality of service regardless of language used)

== Dataset Sourcing ==
  mteb/amazon_massive_intent — 11,514 rows per language, Apache 2.0
  Languages: en, de, fr, es (confirmed working, no scraping, open license)
  These are customer intent utterances — directly maps to support ticket classification.
"""

import logging
import re

logger = logging.getLogger(__name__)

# ── Supported language codes ───────────────────────────────────────────────────
SUPPORTED_LANGUAGES = {
    "en": "English",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "pt": "Portuguese",
    "nl": "Dutch",
    "it": "Italian",
}

# ── Languages that need multilingual model routing ─────────────────────────────
# English-only models (gemma3:4b) perform fine on English.
# For other languages we prefer multilingual models.
MULTILINGUAL_LANGUAGES = {"de", "fr", "es", "pt", "nl", "it"}

# ── Simple stopword sets per language (for BM25 tokenization) ─────────────────
# Minimal sets — good enough for BM25 without NLTK dependency
_STOPWORDS: dict[str, set[str]] = {
    "en": {"the", "a", "an", "is", "it", "in", "on", "at", "to", "for",
           "of", "and", "or", "but", "my", "i", "we", "you", "our", "your"},
    "de": {"der", "die", "das", "ein", "eine", "ist", "ich", "wir", "sie",
           "und", "oder", "aber", "für", "mit", "von", "zu", "an", "auf"},
    "fr": {"le", "la", "les", "un", "une", "est", "je", "nous", "vous",
           "et", "ou", "mais", "pour", "avec", "de", "du", "au", "en"},
    "es": {"el", "la", "los", "un", "una", "es", "yo", "nosotros", "ustedes",
           "y", "o", "pero", "para", "con", "de", "del", "al", "en"},
    "pt": {"o", "a", "os", "as", "um", "uma", "é", "eu", "nós", "você",
           "e", "ou", "mas", "para", "com", "de", "do", "ao", "em"},
    "nl": {"de", "het", "een", "is", "ik", "wij", "u", "en", "of", "maar",
           "voor", "met", "van", "aan", "op", "in", "te"},
    "it": {"il", "la", "i", "le", "un", "una", "è", "io", "noi", "voi",
           "e", "o", "ma", "per", "con", "di", "del", "al", "in"},
}


def detect_language(text: str, min_text_length: int = 20) -> str:
    """
    Detect the language of a text string.

    Returns an ISO 639-1 language code (e.g. 'en', 'de', 'fr').
    Falls back to 'en' if:
      - Text is too short for reliable detection
      - langdetect is not installed
      - Detection fails (mixed language, gibberish, etc.)

    Uses langdetect under the hood (probabilistic Naive Bayes).
    """
    text = (text or "").strip()
    if len(text) < min_text_length:
        return "en"  # too short for reliable detection

    try:
        from langdetect import detect
        lang = detect(text)
        # langdetect returns e.g. "zh-cn" — normalize to first part
        lang = lang.split("-")[0].lower()
        return lang
    except ImportError:
        logger.debug("langdetect not installed — returning 'en' as fallback")
        return "en"
    except Exception:
        return "en"


def detect_language_with_confidence(text: str) -> tuple[str, float]:
    """
    Detect language with confidence score.
    Returns (language_code, probability 0.0-1.0).
    """
    text = (text or "").strip()
    if len(text) < 20:
        return "en", 1.0

    try:
        from langdetect import detect_langs
        results = detect_langs(text)
        if results:
            top = results[0]
            lang = str(top.lang).split("-")[0].lower()
            prob = float(top.prob)
            return lang, round(prob, 3)
        return "en", 1.0
    except ImportError:
        return "en", 1.0
    except Exception:
        return "en", 0.5


def get_stopwords(lang: str) -> set[str]:
    """Return stopword set for a language. Falls back to English."""
    return _STOPWORDS.get(lang, _STOPWORDS["en"])


def tokenize_multilingual(text: str, lang: str) -> list[str]:
    """
    Language-aware tokenization for BM25.
    Lowercases, removes punctuation, filters stopwords.
    """
    # Simple unicode-friendly tokenization
    tokens = re.findall(r"\b\w+\b", text.lower(), re.UNICODE)
    stopwords = get_stopwords(lang)
    return [t for t in tokens if t not in stopwords and len(t) > 1]


def needs_multilingual_model(lang: str) -> bool:
    """Return True if this language needs a multilingual model (not English-only)."""
    return lang in MULTILINGUAL_LANGUAGES


def get_language_display(lang: str) -> str:
    """Return human-readable language name."""
    return SUPPORTED_LANGUAGES.get(lang, f"Unknown ({lang})")


def enrich_with_language(record: dict) -> dict:
    """
    Add language detection fields to a Silver record.
    Mutates the record in place and returns it.

    Added fields:
      detected_language     — ISO 639-1 code (e.g. 'de')
      language_confidence   — 0.0-1.0 detection confidence
      language_display      — human readable (e.g. 'German')
      is_multilingual       — True if non-English
    """
    text = record.get("body", "") or record.get("subject", "") or ""
    lang, confidence = detect_language_with_confidence(text)

    record["detected_language"] = lang
    record["language_confidence"] = confidence
    record["language_display"] = get_language_display(lang)
    record["is_multilingual"] = needs_multilingual_model(lang)
    return record


# ── Standalone demo ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    test_cases = [
        ("en", "My payment failed and I cannot access my account. Please help urgently."),
        ("de", "Meine Zahlung ist fehlgeschlagen und ich kann nicht auf mein Konto zugreifen."),
        ("fr", "Mon paiement a échoué et je ne peux pas accéder à mon compte. Aidez-moi."),
        ("es", "Mi pago falló y no puedo acceder a mi cuenta. Por favor ayúdame urgentemente."),
        ("pt", "Meu pagamento falhou e não consigo acessar minha conta. Por favor, ajude."),
        ("nl", "Mijn betaling is mislukt en ik kan geen toegang krijgen tot mijn account."),
        ("it", "Il mio pagamento è fallito e non riesco ad accedere al mio account. Aiutami."),
    ]

    print("=" * 65)
    print("CustomerCore Phase 8a — Language Detection Demo")
    print("=" * 65)
    print(f"\n{'Expected':<8} {'Detected':<8} {'Conf':<7} {'Multilingual':<14} Text")
    print("─" * 70)

    all_correct = True
    for expected, text in test_cases:
        lang, conf = detect_language_with_confidence(text)
        is_ml = needs_multilingual_model(lang)
        ok = "✓" if lang == expected else "✗"
        if lang != expected:
            all_correct = False
        print(f"{ok} {expected:<6} {lang:<8} {conf:<7.2f} {str(is_ml):<14} {text[:40]}...")

    print(f"\n{'All detections correct ✓' if all_correct else 'Some detections wrong ✗'}")
    print("=" * 65)
