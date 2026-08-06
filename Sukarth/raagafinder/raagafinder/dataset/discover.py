"""Schema discovery: inventory the dataset zip WITHOUT extracting it.

Produces a human-readable report (stdout + work/discovery_report.txt) with:
- member counts/sizes grouped by extension and top-level directory
- directory-shape samples
- heads of candidate metadata files (json/tsv/csv at shallow depth)
- heads of a few sample members per extension

All format assumptions belong in loader.py; this module only reports.
"""

import io
import zipfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

from raagafinder.config import DATASET_ZIP, WORK_DIR

HEAD_BYTES = 400
METADATA_EXTS = {".json", ".tsv", ".csv", ".yaml", ".yml"}
MAX_META_HEAD = 3000


def _ext(name: str) -> str:
    return PurePosixPath(name).suffix.lower() or "<none>"


def discover(zip_path: Path = DATASET_ZIP) -> str:
    out = io.StringIO()
    w = out.write
    with zipfile.ZipFile(zip_path) as zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        w(f"zip: {zip_path}\nmembers (files): {len(infos)}\n")
        w(f"total uncompressed: {sum(i.file_size for i in infos) / 1e9:.2f} GB\n\n")

        by_ext = Counter(_ext(i.filename) for i in infos)
        size_by_ext = defaultdict(int)
        for i in infos:
            size_by_ext[_ext(i.filename)] += i.file_size
        w("== by extension ==\n")
        for ext, n in by_ext.most_common():
            w(f"  {ext:12s} n={n:6d}  {size_by_ext[ext] / 1e9:.3f} GB\n")

        w("\n== top-level dirs ==\n")
        top = Counter(PurePosixPath(i.filename).parts[0] for i in infos)
        for d, n in top.most_common(20):
            w(f"  {d}  ({n} files)\n")

        w("\n== path shape samples (depth-truncated, first 40 unique) ==\n")
        seen = set()
        for i in infos:
            parts = PurePosixPath(i.filename).parts
            shape = "/".join(parts[:4]) + ("/..." if len(parts) > 4 else "")
            if shape not in seen:
                seen.add(shape)
                w(f"  {shape}\n")
                if len(seen) >= 40:
                    break

        w("\n== candidate metadata files (shallow json/tsv/csv) ==\n")
        meta = [
            i for i in infos
            if _ext(i.filename) in METADATA_EXTS and len(PurePosixPath(i.filename).parts) <= 3
        ]
        for i in meta[:15]:
            w(f"\n--- {i.filename} ({i.file_size} B) ---\n")
            with zf.open(i) as f:
                head = f.read(MAX_META_HEAD)
            w(head.decode("utf-8", errors="replace") + "\n")

        w("\n== sample heads per extension ==\n")
        shown: Counter = Counter()
        for i in infos:
            ext = _ext(i.filename)
            if ext in METADATA_EXTS or shown[ext] >= 3:
                continue
            shown[ext] += 1
            w(f"\n--- {i.filename} ({i.file_size} B) ---\n")
            with zf.open(i) as f:
                head = f.read(HEAD_BYTES)
            w(head.decode("utf-8", errors="replace") + "\n")

    report = out.getvalue()
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    (WORK_DIR / "discovery_report.txt").write_text(report, encoding="utf-8")
    return report


if __name__ == "__main__":
    print(discover())
