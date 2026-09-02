"""Sync Opentrons Knowledge releases into committed storage/ docs."""

from __future__ import annotations

import hashlib
import shutil
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.request import urlopen

import zstandard as zstd

from api.knowledge.abouts import DEFAULT_ABOUT_MODEL
from api.knowledge.materialize import materialize_runtime_docs

DEFAULT_KNOWLEDGE_VERSION = "9.0.0-k1"
DEFAULT_ABOUT_MODEL_NAME = DEFAULT_ABOUT_MODEL
DEFAULT_RELEASE_TAG_TEMPLATE = "knowledge-v{version}"
DEFAULT_ARCHIVE_NAME_TEMPLATE = "opentrons-knowledge-{version}.tar.zst"
DEFAULT_DOWNLOAD_URL_TEMPLATE = (
    "https://github.com/Opentrons/knowledge/releases/download/"
    "{release_tag}/{archive_name}"
)
VERSION_MARKER_NAME = ".knowledge-version"


@dataclass(frozen=True)
class KnowledgeRuntimePaths:
    """Committed runtime docs under storage/."""

    version: str
    cache_root: Path
    corpus_root: Path
    runtime_root: Path
    ai_docs_path: Path
    api_docs_path: Path
    api_docs_content_root: Path
    api_docs_struct: Path
    api_level_path: Path

    @property
    def version_marker(self) -> Path:
        return self.api_docs_path / VERSION_MARKER_NAME


def default_cache_root(repo_root: Path) -> Path:
    return repo_root / ".cache" / "opentrons-knowledge"


def default_runtime_root(repo_root: Path) -> Path:
    return repo_root / "storage"


def _archive_name(version: str) -> str:
    return DEFAULT_ARCHIVE_NAME_TEMPLATE.format(version=version)


def _release_tag(version: str) -> str:
    return DEFAULT_RELEASE_TAG_TEMPLATE.format(version=version)


def _download_url(version: str) -> str:
    return DEFAULT_DOWNLOAD_URL_TEMPLATE.format(
        release_tag=_release_tag(version),
        archive_name=_archive_name(version),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_expected_sha256(checksum_path: Path) -> Optional[str]:
    if not checksum_path.is_file():
        return None
    text = checksum_path.read_text(encoding="utf-8").strip()
    if not text:
        return None
    first = text.split()[0]
    if first.startswith("sha256:"):
        return first.split(":", 1)[1]
    return first


def runtime_paths_for(
    *,
    version: str,
    repo_root: Path,
    cache_root: Optional[Path] = None,
) -> KnowledgeRuntimePaths:
    if cache_root is None:
        cache_root = default_cache_root(repo_root)
    runtime_root = default_runtime_root(repo_root)
    api_docs_path = runtime_root / "api_docs"
    return KnowledgeRuntimePaths(
        version=version,
        cache_root=cache_root,
        corpus_root=cache_root / "corpora" / version,
        runtime_root=runtime_root,
        ai_docs_path=runtime_root / "docs",
        api_docs_path=api_docs_path,
        api_docs_content_root=api_docs_path / "docs" / "v2",
        api_docs_struct=api_docs_path / "api_docs_struct.md",
        api_level_path=api_docs_path / ".api-level",
    )


def is_runtime_ready(paths: KnowledgeRuntimePaths, version: str) -> bool:
    if not paths.version_marker.is_file():
        return False
    if paths.version_marker.read_text(encoding="utf-8").strip() != version:
        return False
    if not paths.api_docs_struct.is_file():
        return False
    if not paths.api_docs_content_root.is_dir():
        return False
    if not any(paths.ai_docs_path.glob("*.md")):
        return False
    if not any(paths.api_docs_content_root.rglob("*.md")):
        return False
    return True


def download_archive(version: str, archive_path: Path) -> Path:
    """Download the release tar.zst (and optional .sha256) into archive_path."""
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    checksum_path = Path(str(archive_path) + ".sha256")

    url = _download_url(version)
    with urlopen(url) as response, archive_path.open("wb") as out:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)

    checksum_url = url + ".sha256"
    try:
        with urlopen(checksum_url) as response:
            checksum_path.write_bytes(response.read())
    except Exception:
        pass

    expected = _read_expected_sha256(checksum_path)
    if expected is not None:
        actual = _sha256_file(archive_path)
        if actual != expected:
            raise RuntimeError(
                f"Knowledge archive checksum mismatch for {archive_path}: "
                f"expected {expected}, got {actual}"
            )
    return archive_path


def unpack_archive(archive_path: Path, destination: Path) -> Path:
    """Extract tar.zst into destination (expects manifest.yaml at root)."""
    if destination.exists():
        shutil.rmtree(destination)

    destination.mkdir(parents=True, exist_ok=True)
    decompressor = zstd.ZstdDecompressor()
    # Stream zstd → tar (r|) so we do not buffer the full decompressed archive in memory.
    with archive_path.open("rb") as raw, decompressor.stream_reader(raw) as reader:
        with tarfile.open(fileobj=reader, mode="r|") as tar:
            tar.extractall(destination, filter="data")

    if not (destination / "manifest.yaml").is_file():
        raise RuntimeError(f"Unpack did not produce manifest.yaml under {destination}")
    return destination


def sync_knowledge(
    *,
    version: str = DEFAULT_KNOWLEDGE_VERSION,
    cache_root: Optional[Path] = None,
    repo_root: Optional[Path] = None,
    use_claude_abouts: bool = True,
    about_model: str = DEFAULT_ABOUT_MODEL_NAME,
    anthropic_api_key: Optional[str] = None,
    about_workers: int = 8,
    progress: Optional[Callable[[str], None]] = None,
) -> KnowledgeRuntimePaths:
    """
    Update committed docs from a knowledge release tag.

    1. Download opentrons-knowledge-<version>.tar.zst into .cache/
    2. Unpack the corpus under .cache/
    3. Materialize AI guides + MkDocs API docs into storage/ (commit these)
    4. By default, rewrite api_docs_struct <about> blurbs with Claude
    """
    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent.parent

    if use_claude_abouts and not anthropic_api_key:
        from api.settings import Settings

        anthropic_api_key = Settings().anthropic_api_key.get_secret_value()

    paths = runtime_paths_for(version=version, repo_root=repo_root, cache_root=cache_root)
    archive_path = paths.cache_root / "downloads" / _archive_name(version)

    download_archive(version, archive_path)
    unpack_archive(archive_path, paths.corpus_root)
    materialize_runtime_docs(
        paths.corpus_root,
        paths.runtime_root,
        version=version,
        force=True,
        ai_docs_dirname="docs",
        use_claude_abouts=use_claude_abouts,
        about_model=about_model,
        anthropic_api_key=anthropic_api_key,
        about_workers=about_workers,
        progress=progress or print,
    )

    if not is_runtime_ready(paths, version):
        raise RuntimeError(f"Knowledge sync failed for version {version}")
    return paths


def load_knowledge_runtime(
    *,
    version: str = DEFAULT_KNOWLEDGE_VERSION,
    repo_root: Optional[Path] = None,
) -> KnowledgeRuntimePaths:
    """Load committed storage/ docs. Runtime never downloads."""
    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent.parent

    paths = runtime_paths_for(version=version, repo_root=repo_root)
    if not is_runtime_ready(paths, version):
        raise RuntimeError(
            "Committed knowledge docs are missing or the wrong version. "
            f"Expected {version} under {paths.runtime_root}. "
            f"Run: make sync-knowledge KNOWLEDGE_VERSION={version}"
        )
    return paths
