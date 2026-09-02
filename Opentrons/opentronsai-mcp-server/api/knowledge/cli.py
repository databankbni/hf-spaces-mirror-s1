"""CLI: sync a knowledge release tag into storage/."""

from __future__ import annotations

import argparse
from pathlib import Path

from api.knowledge.abouts import DEFAULT_ABOUT_MODEL
from api.knowledge.cache import DEFAULT_KNOWLEDGE_VERSION, sync_knowledge
from api.settings import Settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Sync docs from an Opentrons Knowledge release: download into .cache/, "
            "materialize into storage/, and (by default) generate Claude <about> blurbs."
        )
    )
    parser.add_argument(
        "--version",
        default=DEFAULT_KNOWLEDGE_VERSION,
        help=(
            "Knowledge corpus version (release tag is knowledge-v<version>). "
            f"Default: {DEFAULT_KNOWLEDGE_VERSION}"
        ),
    )
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=None,
        help="Download/unpack cache directory (default: <repo>/.cache/opentrons-knowledge)",
    )
    parser.add_argument(
        "--no-claude-abouts",
        action="store_true",
        help="Skip Claude about generation; use local extract_about fallbacks only.",
    )
    parser.add_argument(
        "--about-model",
        default=None,
        help=(
            "Anthropic model for <about> generation. "
            f"Default: settings.knowledge_about_model or {DEFAULT_ABOUT_MODEL}"
        ),
    )
    parser.add_argument(
        "--about-workers",
        type=int,
        default=8,
        help="Parallel Claude about requests (default: 8).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings()
    about_model = args.about_model or settings.knowledge_about_model or DEFAULT_ABOUT_MODEL
    paths = sync_knowledge(
        version=args.version,
        cache_root=args.cache_root,
        use_claude_abouts=not args.no_claude_abouts,
        about_model=about_model,
        anthropic_api_key=settings.anthropic_api_key.get_secret_value(),
        about_workers=args.about_workers,
        progress=print,
    )
    print(f"Synced knowledge {paths.version} into storage/ (commit these files)")
    print(f"  downloaded:   {paths.cache_root / 'downloads'}")
    print(f"  unpacked:     {paths.corpus_root}")
    print(f"  ai docs:      {paths.ai_docs_path}")
    print(f"  api docs:     {paths.api_docs_content_root}")
    print(f"  struct:       {paths.api_docs_struct}")
    if args.no_claude_abouts:
        print("  abouts:       extract (local)")
    else:
        print(f"  abouts:       claude ({about_model})")
    if paths.api_level_path.is_file():
        print(f"  apiLevel:     {paths.api_level_path.read_text(encoding='utf-8').strip()}")
    print(f"  version file: {paths.version_marker}")
    return 0
