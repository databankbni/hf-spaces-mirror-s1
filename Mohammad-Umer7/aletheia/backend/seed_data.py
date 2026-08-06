"""Demo scenario content. ALL of it is fictional — no real brands, journals, or people.

Text is verbatim from the build spec (section 9); do not edit casually, the flip
test's narrative depends on it.
"""

DEMO_QUESTION = "Does Mnemosyne-7 improve memory? What actually works?"

SEED_SOURCES = [
    {
        "id": "helios_study",
        "kind": "study",
        "title": "Helios Longevity Institute trial (2025)",
        "text": (
            "Helios Longevity Institute, 2025 — In a 12-week internal trial of 240 adults, "
            "daily Mnemosyne-7 supplementation improved verbal recall scores by 40% versus "
            "placebo. Lead researcher Dr. R. Calder called it 'the largest effect ever "
            "recorded for an over-the-counter memory supplement.' The Institute notes that "
            "Mnemosyne-7 is available for purchase directly from its online store."
        ),
    },
    {
        "id": "meridian_post",
        "kind": "news",
        "title": "Meridian Post: 'The end of forgetting?' (2025)",
        "text": (
            "Meridian Post, 2025 — A new study from the Helios Longevity Institute claims "
            "the supplement Mnemosyne-7 boosts memory by 40%. 'This could change aging "
            "itself,' said lead researcher Dr. R. Calder. Sales of Mnemosyne-7 have surged "
            "since the announcement, and retailers report waiting lists."
        ),
    },
    {
        "id": "jch_retraction",
        "kind": "retraction",
        "title": "Journal of Cognitive Health — Retraction notice (2026)",
        "text": (
            "Journal of Cognitive Health, 2026 — RETRACTION: The Helios Longevity Institute "
            "trial of Mnemosyne-7 has been retracted after independent auditors found "
            "fabricated placebo-group data and an undisclosed financial conflict of "
            "interest: the Institute manufactures and sells Mnemosyne-7. The reported 40% "
            "memory-improvement claim should be considered unsupported by evidence."
        ),
    },
    {
        "id": "northfield_meta",
        "kind": "meta-analysis",
        "title": "Northfield University meta-analysis (2024)",
        "text": (
            "Northfield University, 2024 — A meta-analysis of 61 randomized controlled "
            "trials finds that consistent aerobic exercise (three or more sessions per "
            "week) and regular 7-9 hour sleep show the strongest and most replicated "
            "effects on memory consolidation in healthy adults. Evidence for "
            "over-the-counter memory supplements remains weak and inconsistent."
        ),
    },
]
