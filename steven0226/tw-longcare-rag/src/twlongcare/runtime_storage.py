"""Bootstrap immutable seed data into an optional persistent runtime volume."""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from .config import DATA_DIR, REPO_ROOT

SEED_FILES = (
    "laws.json",
    "contextual_cache.json",
    "chapter_summaries.json",
    "law_graph.json",
    "testset.json",
    "law_version_manifest.json",
)
SEED_TREES = ("versions/laws",)


def _copy_missing_file(source: Path, destination: Path) -> str:
    """Create destination without replacing a file another process published."""
    if destination.exists():
        return "preserved"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.bootstrap-{os.getpid()}-{uuid.uuid4().hex}.tmp"
    )
    try:
        shutil.copy2(source, temporary)
        try:
            # A hard link atomically creates the final name and fails if it exists.
            os.link(temporary, destination)
            return "copied"
        except FileExistsError:
            return "preserved"
        except OSError:
            # Some object-backed volume drivers do not support hard links. An
            # exclusive create still guarantees that persistent data is never
            # overwritten; bootstrap runs before the app serves requests.
            try:
                with source.open("rb") as source_handle:
                    descriptor = os.open(
                        destination,
                        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                        0o644,
                    )
                    try:
                        with os.fdopen(descriptor, "wb") as destination_handle:
                            shutil.copyfileobj(source_handle, destination_handle)
                            destination_handle.flush()
                            os.fsync(destination_handle.fileno())
                    except BaseException:
                        destination.unlink(missing_ok=True)
                        raise
                return "copied"
            except FileExistsError:
                return "preserved"
    finally:
        temporary.unlink(missing_ok=True)


def bootstrap_runtime_data(
    *,
    seed_dir: Path = REPO_ROOT / "data",
    runtime_dir: Path = DATA_DIR,
) -> dict[str, Any]:
    """Copy only missing, deployable seed data into a mounted runtime directory."""
    seed_dir = seed_dir.resolve()
    runtime_dir = runtime_dir.resolve()
    report: dict[str, Any] = {
        "schema_version": "runtime-storage-bootstrap-v1",
        "seed_dir": str(seed_dir),
        "runtime_dir": str(runtime_dir),
        "same_directory": seed_dir == runtime_dir,
        "copied": [],
        "preserved": [],
        "missing_seed": [],
    }
    if seed_dir == runtime_dir:
        if not (runtime_dir / "laws.json").exists():
            raise FileNotFoundError(f"missing required law corpus: {runtime_dir / 'laws.json'}")
        return report

    candidates = [Path(relative) for relative in SEED_FILES]
    for relative_tree in SEED_TREES:
        source_tree = seed_dir / relative_tree
        if not source_tree.exists():
            report["missing_seed"].append(relative_tree)
            continue
        candidates.extend(
            path.relative_to(seed_dir)
            for path in sorted(source_tree.rglob("*"))
            if path.is_file()
        )

    for relative in candidates:
        source = seed_dir / relative
        relative_name = relative.as_posix()
        if not source.is_file():
            report["missing_seed"].append(relative_name)
            continue
        status = _copy_missing_file(source, runtime_dir / relative)
        report[status].append(relative_name)

    required = runtime_dir / "laws.json"
    if not required.exists():
        raise FileNotFoundError(
            f"runtime bootstrap could not provide required law corpus: {required}"
        )
    return report
