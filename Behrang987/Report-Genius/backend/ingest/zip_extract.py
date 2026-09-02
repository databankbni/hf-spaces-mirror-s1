"""Safe extraction of .docx / .pdf members from a ZIP archive (zip-slip hardened)."""

from __future__ import annotations

import zipfile
from pathlib import Path

from backend.config import settings


def extract_reference_documents(
    zip_path: Path, dest_dir: Path
) -> list[tuple[str, Path]]:
    """Extract allowed document types from ``zip_path`` into ``dest_dir``.

    Filenames are flattened to a single directory with collision-safe names.
    Enforces upload size limits from settings.
    """
    dest_dir = dest_dir.resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)

    out: list[tuple[str, Path]] = []
    used_names: set[str] = set()

    with zipfile.ZipFile(zip_path) as zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > settings.max_zip_members:
            raise ValueError(
                f"ZIP contains {len(infos)} files; maximum allowed is {settings.max_zip_members}."
            )

        total_uncompressed = sum(int(i.file_size) for i in infos)
        if total_uncompressed > settings.max_zip_uncompressed_bytes:
            raise ValueError(
                "ZIP uncompressed size exceeds configured limit "
                f"({settings.max_zip_uncompressed_bytes} bytes)."
            )

        for info in infos:
            suffix = Path(info.filename).suffix.lower()
            if suffix not in {".docx", ".pdf", ".doc", ".docm"}:
                continue

            raw_name = Path(info.filename).name
            if not raw_name or raw_name.startswith("."):
                continue
            if ".." in info.filename.replace("\\", "/"):
                continue

            base = raw_name
            final_name = base
            n = 0
            while final_name in used_names:
                n += 1
                stem = Path(base).stem
                suf = Path(base).suffix
                final_name = f"{stem}_{n}{suf}"
            used_names.add(final_name)
            target = dest_dir / final_name

            oversized = False
            with zf.open(info, "r") as src, open(target, "wb") as dst:
                written = 0
                chunk = 1024 * 1024
                while True:
                    block = src.read(chunk)
                    if not block:
                        break
                    written += len(block)
                    if written > settings.max_single_upload_bytes:
                        oversized = True
                        break
                    dst.write(block)

            if oversized:
                target.unlink(missing_ok=True)
                raise ValueError(
                    f"Single file inside ZIP exceeds max size "
                    f"({settings.max_single_upload_bytes} bytes): {info.filename!r}"
                )

            out.append((info.filename, target))

    return out
