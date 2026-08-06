# ---------------------------------------------------------------------------
# ingestion/fetch_dataset.py — Phase A1.
#
# Pull `OEvortex/Bhagavad_Gita` from the Hugging Face Hub and normalize it
# into clean per-verse rows the rest of the app understands.
#
# Source schema (verified via the datasets-server API):
#   S.No.              int
#   Title              str   e.g. "Arjuna's Vishada Yoga"
#   Chapter            str   e.g. "Chapter 1"
#   Verse              str   e.g. "Verse 1.1"
#   Sanskrit Anuvad    str   the shloka
#   Hindi Anuvad       str
#   Enlgish Translation str  (NOTE: the column name is misspelled upstream)
#
# Normalized row:
#   {verse_id, chapter, verse, title, sanskrit, english, hindi}
# ---------------------------------------------------------------------------

import re

# Column name as it appears upstream — misspelled on purpose to match.
_ENGLISH_COL = "Enlgish Translation"


def _parse_int(text: str) -> int:
    """Extract the first integer from a string like 'Chapter 1' → 1."""
    m = re.search(r"\d+", str(text))
    if not m:
        raise ValueError(f"No integer found in {text!r}")
    return int(m.group())


def _parse_verse_number(text: str) -> int:
    """Extract the verse number from 'Verse 1.2' → 2 (the part after the dot)."""
    m = re.search(r"\d+\s*\.\s*(\d+)", str(text))
    if m:
        return int(m.group(1))
    # Fallback: some rows may store just a bare number.
    return _parse_int(text)


def normalize_row(row: dict) -> dict:
    """Convert one raw dataset row into the normalized internal schema."""
    chapter = _parse_int(row["Chapter"])
    verse = _parse_verse_number(row["Verse"])
    return {
        "verse_id": f"BG{chapter}.{verse}",
        "chapter": chapter,
        "verse": verse,
        "title": str(row.get("Title", "")).strip(),
        "sanskrit": str(row.get("Sanskrit Anuvad", "")).strip(),
        "english": str(row.get(_ENGLISH_COL, "")).strip(),
        "hindi": str(row.get("Hindi Anuvad", "")).strip(),
    }


def fetch_verses() -> list[dict]:
    """Download the dataset and return a list of normalized verse rows,
    sorted by (chapter, verse). Requires network on first run; the HF
    `datasets` cache makes subsequent runs offline-friendly."""
    from datasets import load_dataset  # imported lazily — heavy dependency

    from config import HF_DATASET_ID

    ds = load_dataset(HF_DATASET_ID, split="train")
    rows = [normalize_row(r) for r in ds]
    rows.sort(key=lambda r: (r["chapter"], r["verse"]))
    return rows


if __name__ == "__main__":
    verses = fetch_verses()
    print(f"[fetch_dataset] fetched {len(verses)} verses")
    sample = verses[0]
    print(f"[fetch_dataset] first: {sample['verse_id']} ({sample['title']})")
    print(f"[fetch_dataset]   sanskrit: {sample['sanskrit'][:60]}...")
    print(f"[fetch_dataset]   english:  {sample['english'][:60]}...")
