"""Small safety helper for the educational symptom-classification project.

The rules are intentionally short and readable. They do not represent a
complete medical triage protocol and cannot determine that a situation is safe.
"""

from __future__ import annotations

import re


# Final display categories
CATEGORY_EMERGENCY = "U1 - Emergency warning signs"
CATEGORY_PROMPT = "U2 - Prompt medical evaluation"
CATEGORY_ROUTINE = "U3 - Routine medical follow-up"
CATEGORY_SELF_CARE = "U4 - General self-care and monitoring"
CATEGORY_UNCERTAIN = "U5 - Uncertain: professional guidance recommended"


# The three labels sent to the zero-shot classifier.
MODEL_LABEL_TO_CATEGORY = {
    "symptoms needing prompt medical evaluation": CATEGORY_PROMPT,
    "symptoms suitable for routine medical follow-up": CATEGORY_ROUTINE,
    "lower-urgency symptoms where general self-care and monitoring may be reasonable": CATEGORY_SELF_CARE,
}


# A deliberately short list of obvious warning phrases.
WARNING_PHRASES = {
    "Severe breathing problem": (
        "cannot breathe",
        "can't breathe",
        "severe trouble breathing",
        "severe difficulty breathing",
        "gasping for air",
        "suffocating",
        "struggling to breathe",
        "choking",
    ),
    "Unresponsiveness": (
        "unconscious",
        "unresponsive",
        "cannot wake",
        "can't wake",
        "passed out",
        "blacked out",
        "not waking up",
        "fainted and not waking",
        "fainted and unresponsive",
        "lost consciousness and not waking",
        "lost consciousness and unresponsive",
    ),
    "Possible stroke warning": (
        "facial droop",
        "one-sided weakness",
        "slurred speech",
        "cannot speak",
        "can't speak",
        "trouble speaking",
        "trouble talking",
        "trouble moving one side",
        "drooping face",
        "drooping mouth",
    ),
    "Major bleeding": (
        "bleeding will not stop",
        "uncontrolled bleeding",
        "bleeding heavily",
        "bleeding profusely",
        "bleeding a lot",
        "hemorrhage",
        "bleeding and cannot stop",
        "bleeding and cannot control",
        "bleeding and can't stop",
        "bleeding and can't control",
        "so much blood",
        "blood everywhere",
        "blood is gushing",
        "blood is pouring",
        "blood is spurting",
    ),
    "Severe allergic reaction": (
        "severe allergic reaction",
        "swelling of the tongue",
        "swelling of the face",
        "swelling of the throat",
        "swelling of the lips",
        "swelling of the mouth",
        "swelling of the eyes",
        "throat closing",
        "throat swelling",
        "throat tight",
    ),
    "Self-harm or harm-to-others concern": (
        "suicidal",
        "homicidal",
        "kill myself",
        "harm myself",
        "kill someone",
        "harm someone",
        "want to die",
        "want to kill",
        "want to hurt myself",
        "want to hurt someone",
        "want to commit suicide",
        "want to commit homicide",
        "take my own life",
        "take someone else's life",
        "want to end my life",
        "want to end someone else's life",
    ),
    "Possible poisoning or overdose": (
        "overdose",
        "poisoned",
        "swallowed poison",
        "ingested poison",
        "ingested all the pills",
        "ingested all the drugs",
        "ingested too many pills",
        "ingested too many drugs",
        "ingested too much medicine",
        "ingested all the medicine",
        "ingested too much alcohol",
        "took too much medicine",
        "took too much drug",
        "took too much alcohol",
        "took too many pills",
        "took too many drugs",
        "swallowed too many pills",
        "swallowed too many drugs",
        "swallowed too much medicine",
        "swallowed all the pills",
        "swallowed all the drugs",
        "ate all the pills",
        "ate all the drugs",
        "ate too many pills",
        "ate too many drugs",
        "ate too much medicine",
    ),
    "Seizure with persistent unresponsiveness": (
        "seizure and not waking",
        "seizure and unresponsive",
        "seizure and cannot wake",
        "seizure and can't wake",
        "seizure and unconscious",
        "seizure and passed out",
        "seizure and blacked out",
    ),
    "Concerning chest symptoms": (
        "crushing chest pain",
        "chest pressure with sweating",
        "chest pressure with nausea",
        "chest pressure with vomiting",
        "chest pressure with shortness of breath",
        "chest pressure with trouble breathing",
        "chest pressure with lightheadedness",
        "chest pressure with dizziness",
        "chest pressure with fainting",
        "chest pressure with palpitations",
        "chest pressure with racing heart",
        "chest pressure with irregular heartbeat",
        "chest pain with sweating",
        "chest pain with nausea",
        "chest pain with vomiting",
        "chest pain with shortness of breath",
        "chest pain with trouble breathing",
        "chest pain with lightheadedness",
        "chest pain with dizziness",
        "chest pain with fainting",
        "chest pain with palpitations",
        "chest pain with racing heart",
        "chest pain with irregular heartbeat",
    ),
}


NEGATION_WORDS = {"no", "not", "never", "without", "denies", "denied"}
MINIMUM_WORDS = 6
DEMO_CONFIDENCE_THRESHOLD = 0.50


EMERGENCY_RESOURCES = """This application is for educational purposes only. If this may be an actual emergency, use the appropriate resource:
- Immediate danger or medical emergency: call local emergency services. In the United States, call 911.
- Suicide or mental-health crisis: in the United States, call or text 988. If there is immediate danger, call 911.
- Suspected poisoning or overdose: in the United States, call Poison Help at 1-800-222-1222. If the person has collapsed, had a seizure, has trouble breathing, or cannot be awakened, call 911 immediately.
- Outside the United States: use the appropriate local emergency, crisis, or poison service."""


def normalize_text(text: str) -> str:
    """Lowercase text and replace repeated whitespace with single spaces."""

    return " ".join((text or "").lower().split())


def input_is_too_short(text: str) -> bool:
    """Return True when the narrative is too short for the demonstration."""

    words = re.findall(r"[a-zA-Z']+", text or "")
    return len(words) < MINIMUM_WORDS


def phrase_is_negated(text: str, phrase_start: int) -> bool:
    """Check the three words immediately before a warning phrase.

    This is a small convenience for inputs such as "no trouble breathing."
    It is not a complete clinical negation algorithm.
    """

    earlier_words = re.findall(r"[a-z']+", text[:phrase_start])
    return any(word in NEGATION_WORDS for word in earlier_words[-3:])


def detect_warning_phrases(text: str) -> list[str]:
    """Return non-negated warning phrases found in the input."""

    normalized = normalize_text(text)
    matches = []

    for warning_group, phrases in WARNING_PHRASES.items():
        for phrase in phrases:
            phrase_start = normalized.find(phrase)
            if phrase_start >= 0 and not phrase_is_negated(normalized, phrase_start):
                matches.append(f"{warning_group}: {phrase}")
                break

    return matches


def choose_final_result(
    text: str,
    model_label: str | None = None,
    confidence: float | None = None,
) -> dict:
    """Combine simple input checks, warning phrases, and a model result."""

    warning_matches = detect_warning_phrases(text)

    if warning_matches:
        category = CATEGORY_EMERGENCY
        reason = "A warning phrase triggered the educational emergency override."
    elif input_is_too_short(text):
        category = CATEGORY_UNCERTAIN
        reason = f"Please enter at least {MINIMUM_WORDS} words."
    elif model_label not in MODEL_LABEL_TO_CATEGORY or confidence is None:
        category = CATEGORY_UNCERTAIN
        reason = "A usable model classification was not available."
    elif confidence < DEMO_CONFIDENCE_THRESHOLD:
        category = CATEGORY_UNCERTAIN
        reason = "The model classification confidence was below the demonstration threshold."
    else:
        category = MODEL_LABEL_TO_CATEGORY[model_label]
        reason = "The category was selected by the zero-shot text classifier."

    show_emergency_resources = category in {CATEGORY_EMERGENCY, CATEGORY_PROMPT}

    return {
        "category": category,
        "reason": reason,
        "warning_phrases": warning_matches,
        "show_emergency_resources": show_emergency_resources,
        "emergency_resources": EMERGENCY_RESOURCES if show_emergency_resources else "",
    }
