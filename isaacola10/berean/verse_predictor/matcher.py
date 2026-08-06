"""Hybrid, multilingual verse retrieval.

Pipeline: optional exact-reference shortcut -> semantic search (int8 index)
-> lexical re-rank -> optional cross-encoder re-rank -> group by canonical
verse key (so the same verse across translations/languages collapses into one
hit, with every translation attached).
"""
import json
import os
from pathlib import Path

import numpy as np
from rapidfuzz import fuzz

from build_index import EMB_FILE, META_FILE, MODEL_NAME, SCALE_FILE
from reference import parse_reference

CROSSREFS_FILE = Path(__file__).parent / "crossrefs.json"

# Canonical book-number ranges for scope filtering.
SCOPES: dict[str, set[int] | None] = {
    "all": None,
    "ot": set(range(1, 40)),
    "nt": set(range(40, 67)),
    "torah": set(range(1, 6)),
    "history": set(range(6, 18)),
    "wisdom": set(range(18, 23)),
    "prophets": set(range(23, 40)),
    "gospels": set(range(40, 44)),
    "epistles": set(range(45, 66)),
}

# Default blend weights. `semantic`/`lexical` apply when the cross-encoder is
# unavailable; the `ce*` set applies when it runs. The admin "search lab" can
# override these live via set_weights().
DEFAULT_WEIGHTS = {
    "semantic": 0.65, "lexical": 0.35,
    "ce": 0.60, "ce_semantic": 0.25, "ce_lexical": 0.15,
}
WEIGHTS = dict(DEFAULT_WEIGHTS)


def set_weights(w: dict):
    """Update the live ranking weights (admin search lab)."""
    for k in DEFAULT_WEIGHTS:
        if k in w and w[k] is not None:
            WEIGHTS[k] = float(w[k])

RERANK_K = 150          # semantic candidates pulled for lexical re-rank
CROSS_ENCODER_K = 40    # of those, how many the cross-encoder scores
CROSS_ENCODER_NAME = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"

# Enable the cross-encoder unless explicitly disabled (RERANK=0).
USE_CROSS_ENCODER = os.environ.get("RERANK", "1") != "0"


class VerseMatcher:
    def __init__(self):
        if not EMB_FILE.exists():
            raise FileNotFoundError(
                "Embedding cache not found. Run:  python build_index.py"
            )
        from sentence_transformers import SentenceTransformer

        # Dequantize int8 index back to float32 for fast scoring.
        q = np.load(EMB_FILE)
        scale = float(np.load(SCALE_FILE))
        self.embeddings = q.astype(np.float32) * scale
        self.meta = np.load(META_FILE, allow_pickle=True)
        self.model = SentenceTransformer(MODEL_NAME)
        self._cross_encoder = None  # lazy

        self.versions = np.array([m["version"] for m in self.meta])
        self.languages = np.array([m["language"] for m in self.meta])
        self.book_nos = np.array([m["book_no"] for m in self.meta])
        self.available_versions = sorted(set(self.versions.tolist()))

        # canonical key -> {version: verse dict}; plus chapter + book indexes.
        self.by_key: dict[str, dict[str, dict]] = {}
        self.chapters: dict[tuple, list[dict]] = {}
        self.book_name: dict[int, str] = {}
        self.key_to_row: dict[str, int] = {}  # representative row per verse
        for idx, m in enumerate(self.meta):
            key = m["key"]
            self.by_key.setdefault(key, {})[m["version"]] = m
            self.chapters.setdefault((m["version"], m["book_no"], m["chapter"]), []).append(m)
            if m["language"] == "en":
                self.book_name[m["book_no"]] = m["book"]
            if key not in self.key_to_row or m["version"] == "KJV":
                self.key_to_row[key] = idx
        for verses in self.chapters.values():
            verses.sort(key=lambda x: x["verse"])

        # Cross-references (openbible, CC-BY): key -> [target keys].
        self.crossrefs: dict[str, list[str]] = {}
        if CROSSREFS_FILE.exists():
            self.crossrefs = json.loads(CROSSREFS_FILE.read_text())

    # -- cross-encoder ----------------------------------------------------
    def _ce(self):
        if self._cross_encoder is None:
            from sentence_transformers import CrossEncoder

            self._cross_encoder = CrossEncoder(CROSS_ENCODER_NAME)
        return self._cross_encoder

    # -- helpers ----------------------------------------------------------
    def _translations_for(self, key: str, best_version: str) -> list[dict]:
        items = self.by_key.get(key, {})
        ordered = sorted(items.items(), key=lambda kv: (kv[0] != best_version, kv[0]))
        return [
            {
                "version": v,
                "language": m["language"],
                "ref": m["ref"],
                "text": m["text"],
            }
            for v, m in ordered
        ]

    def _result_for_key(self, key: str, query: str, version: str,
                        score: float, sem: float, lex: float, exact: bool):
        """Build a grouped result, picking the best version for the verse."""
        candidates = self.by_key.get(key, {})
        if version != "all" and version in candidates:
            best_version = version
        else:
            # Prefer the translation that actually *contains* the quoted words
            # (partial_ratio rewards substring alignment, so reciting YLT
            # surfaces YLT rather than whichever embedding happened to win).
            best_version = max(
                candidates,
                key=lambda v: (
                    fuzz.partial_ratio(query.lower(), candidates[v]["text"].lower()),
                    v == "KJV",                       # tie-break: prefer KJV
                    candidates[v]["language"] == "en",  # then any English
                ),
            )
        m = candidates[best_version]
        return {
            "key": key,
            "ref": m["ref"],
            "version": best_version,
            "language": m["language"],
            "text": m["text"],
            "score": score,
            "semantic": sem,
            "lexical": lex,
            "exact": exact,
            "translations": self._translations_for(key, best_version),
        }

    # -- chapter / context ------------------------------------------------
    def get_chapter(self, book_no: int, chapter: int, version: str) -> dict | None:
        verses = self.chapters.get((version, book_no, chapter))
        if not verses:
            return None
        return {
            "version": version,
            "book": self.book_name.get(book_no, verses[0]["book"]),
            "book_no": book_no,
            "chapter": chapter,
            "verses": [
                {"verse": v["verse"], "ref": v["ref"], "text": v["text"]}
                for v in verses
            ],
        }

    def resolve_reference(self, query: str):
        """(book_no, chapter, verse|None) if the query names a reference."""
        return parse_reference(query)

    # -- cross-references / similar verses --------------------------------
    def _resolve_key(self, key: str, version: str) -> dict | None:
        cand = self.by_key.get(key)
        if not cand:
            return None
        if version != "all" and version in cand:
            v = version
        elif "KJV" in cand:
            v = "KJV"
        else:
            v = next(iter(cand))
        m = cand[v]
        bn, ch, vs = (int(x) for x in key.split(":"))
        return {
            "key": key, "ref": m["ref"], "version": v, "text": m["text"],
            "book_no": bn, "chapter": ch, "verse": vs,
        }

    def get_crossrefs(self, key: str, version: str = "all") -> list[dict]:
        out = []
        for k in self.crossrefs.get(key, []):
            r = self._resolve_key(k, version)
            if r:
                out.append(r)
        return out

    def similar(self, key: str, top_k: int = 6, version: str = "all") -> list[dict]:
        row = self.key_to_row.get(key)
        if row is None:
            return []
        q = self.embeddings[row]
        sem = self.embeddings @ q
        pool = (
            np.where(self.versions == version)[0]
            if version != "all"
            else np.arange(self.embeddings.shape[0])
        )
        if pool.size == 0:
            return []
        k = min(RERANK_K, pool.size)
        cand = pool[np.argpartition(-sem[pool], k - 1)[:k]]
        cand = cand[np.argsort(-sem[cand])]
        results, seen = [], {key}
        for i in cand:
            kk = self.meta[i]["key"]
            if kk in seen:
                continue
            seen.add(kk)
            results.append(
                self._result_for_key(kk, "", version, float(sem[i]), float(sem[i]), 0.0, exact=False)
            )
            if len(results) >= top_k:
                break
        return results

    # -- main search ------------------------------------------------------
    def predict(self, query: str, top_k: int = 5, version: str = "all",
                scope: str = "all", weights: dict | None = None):
        w = weights or WEIGHTS
        query = (query or "").strip()
        if not query:
            return []

        # 1. Exact reference shortcut ("John 3:16"). Explicit refs ignore scope.
        ref = parse_reference(query)
        if ref and ref[2] is not None:
            book_no, chapter, verse = ref
            key = f"{book_no}:{chapter}:{verse}"
            if key in self.by_key:
                # A bare reference has no wording to prefer a version by, so
                # default to KJV when the user hasn't picked one.
                eff = version
                if version == "all" and "KJV" in self.by_key[key]:
                    eff = "KJV"
                return [
                    self._result_for_key(
                        key, query, eff, score=1.0, sem=1.0, lex=1.0, exact=True
                    )
                ]

        # 2. Semantic search over the (filtered) pool.
        q = self.model.encode(
            [query], convert_to_numpy=True, normalize_embeddings=True
        ).astype("float32")[0]
        sem = self.embeddings @ q

        mask = np.ones(self.embeddings.shape[0], dtype=bool)
        if version != "all":
            mask &= self.versions == version
        books = SCOPES.get(scope)
        if books is not None:
            mask &= np.isin(self.book_nos, list(books))
        pool = np.where(mask)[0]
        if pool.size == 0:
            return []

        k = min(RERANK_K, pool.size)
        local_top = np.argpartition(-sem[pool], k - 1)[:k]
        cand_idx = pool[local_top]

        # 3. Lexical re-rank.
        rows = []
        for i in cand_idx:
            m = self.meta[i]
            lex = fuzz.token_set_ratio(query, m["text"]) / 100.0
            rows.append({"i": int(i), "m": m, "sem": float(sem[i]), "lex": lex, "ce": 0.0})
        rows.sort(key=lambda r: w["semantic"] * r["sem"] + w["lexical"] * r["lex"],
                  reverse=True)

        def hybrid(r):
            return w["semantic"] * r["sem"] + w["lexical"] * r["lex"]

        # 4. Optional cross-encoder re-rank on the lexical top slice.
        if USE_CROSS_ENCODER and rows:
            slice_ = rows[:CROSS_ENCODER_K]
            try:
                ce = self._ce()
                logits = ce.predict([(query, r["m"]["text"]) for r in slice_])
                probs = 1.0 / (1.0 + np.exp(-np.asarray(logits)))
                for r, p in zip(slice_, probs):
                    r["ce"] = float(p)
                    r["score"] = (
                        w["ce"] * float(p)
                        + w["ce_semantic"] * r["sem"]
                        + w["ce_lexical"] * r["lex"]
                    )
                for r in rows[CROSS_ENCODER_K:]:
                    r["score"] = hybrid(r)
                rows.sort(key=lambda r: r["score"], reverse=True)
            except Exception:  # noqa: BLE001 - fall back to hybrid score
                for r in rows:
                    r["score"] = hybrid(r)
        else:
            for r in rows:
                r["score"] = hybrid(r)

        # 5. Group by canonical verse key.
        results = []
        seen: set[str] = set()
        for r in rows:
            key = r["m"]["key"]
            if key in seen:
                continue
            seen.add(key)
            res = self._result_for_key(
                key, query, version, r["score"], r["sem"], r["lex"], exact=False
            )
            res["ce"] = r["ce"]
            results.append(res)
            if len(results) >= top_k:
                break
        return results


if __name__ == "__main__":
    import sys

    m = VerseMatcher()
    print("Versions:", m.available_versions)
    q = " ".join(sys.argv[1:]) or "for God so loved the world"
    print(f"Query: {q!r}\n")
    for r in m.predict(q):
        tag = " (exact)" if r["exact"] else ""
        print(f"  {r['score']:.3f}  {r['ref']}  [{r['version']}/{r['language']}]{tag}")
        print(f"         {r['text'][:80]}")
