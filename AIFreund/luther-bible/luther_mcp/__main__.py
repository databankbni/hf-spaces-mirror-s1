"""
__main__.py — Entry point for `python -m luther_mcp`.

Usage:
    python -m luther_mcp                    # start MCP server via stdio (default)
    python -m luther_mcp serve              # start MCP server via stdio (explicit)
    python -m luther_mcp --sse              # start MCP server via SSE (HTTP)
    python -m luther_mcp index [--force]    # run the indexer
    python -m luther_mcp download [--force] # download pre-built ChromaDB
"""

import os
import sys


def main():
    args = sys.argv[1:]

    # SSE mode: explicit flag or PORT env var (HuggingFace Spaces sets PORT=7860)
    if "--sse" in args or os.environ.get("PORT"):
        import asyncio
        from luther_mcp.server import main_sse
        port = int(os.environ.get("PORT", 7860))
        asyncio.run(main_sse(port=port))

    elif not args or args[0] == "serve":
        import asyncio
        from luther_mcp.server import main as run
        asyncio.run(run())

    elif args[0] == "index":
        sys.argv = [sys.argv[0]] + args[1:]
        from luther_mcp.indexer import main as run
        run()

    elif args[0] == "download":
        sys.argv = [sys.argv[0]] + args[1:]
        from luther_mcp.downloader import main as run
        run()

    else:
        print(
            f"Unknown subcommand: {args[0]}\n"
            "Usage: python -m luther_mcp [serve|index [--force]|download [--force]|--sse]",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
