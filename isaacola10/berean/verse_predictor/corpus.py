"""Load Bible verses from every translation in data/versions/.

Each translation is one JSON file (scrollmapper format) named by its code,
e.g. data/versions/KJV.json. data/versions/manifest.json holds each version's
display name and language. Drop in a new file + manifest entry and it is
picked up automatically — the corpus is fully dynamic and multilingual.

Every verse carries a canonical `key` ("book_no:chapter:verse", with book_no
the 1-based position Genesis=1 ... Revelation=66) so the same verse lines up
across languages even though book names differ (John 3:16 / Juan 3:16).
"""
import json
import re
from pathlib import Path

VERSIONS_DIR = Path(__file__).parent / "data" / "versions"
MANIFEST = VERSIONS_DIR / "manifest.json"

_WS = re.compile(r"\s+")


def clean(text: str) -> str:
    return _WS.sub(" ", text).strip()


def load_manifest() -> dict[str, dict]:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text())
    return {}


def list_versions() -> list[str]:
    """Available translation codes, sorted. Prefers the manifest so version
    listing works even when only the prebuilt index (not the source JSONs) is
    present."""
    manifest = load_manifest()
    if manifest:
        return sorted(manifest.keys())
    if not VERSIONS_DIR.exists():
        return []
    return sorted(p.stem for p in VERSIONS_DIR.glob("*.json") if p.stem != "manifest")


def version_info() -> list[dict]:
    """[{code, name, language}] for every available version."""
    manifest = load_manifest()
    out = []
    for code in list_versions():
        meta = manifest.get(code, {})
        out.append(
            {
                "code": code,
                "name": meta.get("name", code),
                "language": meta.get("language", "en"),
            }
        )
    return out


def _load_one(path: Path, version: str, language: str):
    with open(path, encoding="utf-8-sig") as f:
        data = json.load(f)
    for book_no, book in enumerate(data["books"], start=1):
        name = book["name"]
        for chapter in book["chapters"]:
            ci = chapter["chapter"]
            for v in chapter["verses"]:
                yield {
                    "version": version,
                    "language": language,
                    "book_no": book_no,
                    "key": f"{book_no}:{ci}:{v['verse']}",
                    "ref": v.get("name") or f"{name} {ci}:{v['verse']}",
                    "book": name,
                    "chapter": ci,
                    "verse": v["verse"],
                    "text": clean(v["text"]),
                }


def load_verses(versions: list[str] | None = None) -> list[dict]:
    """Flat list of verse dicts across the requested versions (all by default)."""
    available = list_versions()
    if not available:
        raise FileNotFoundError(
            f"No translations found in {VERSIONS_DIR}. Run download_versions.py."
        )
    manifest = load_manifest()
    chosen = versions or available

    verses: list[dict] = []
    for version in chosen:
        path = VERSIONS_DIR / f"{version}.json"
        if not path.exists():
            continue
        language = manifest.get(version, {}).get("language", "en")
        verses.extend(_load_one(path, version, language))
    return verses


def canonical_book_names() -> list[str]:
    """Book names in canonical order from an English version (for references)."""
    manifest = load_manifest()
    english = [c for c in list_versions() if manifest.get(c, {}).get("language") == "en"]
    source = english[0] if english else (list_versions()[0] if list_versions() else None)
    if not source:
        return []
    with open(VERSIONS_DIR / f"{source}.json", encoding="utf-8-sig") as f:
        data = json.load(f)
    return [b["name"] for b in data["books"]]


if __name__ == "__main__":
    print("Versions:", version_info())
    v = load_verses()
    print(f"Loaded {len(v)} verses total")
    print(v[0]["version"], v[0]["key"], v[0]["ref"], "->", v[0]["text"][:50])
