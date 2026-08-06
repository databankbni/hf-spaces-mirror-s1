"""Full reset: wipe all cognee memory plus Aletheia runtime state (registry, changelog)."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import memory


async def main() -> None:
    try:
        print(f"cognee wiped: {await memory.forget_everything()}")
    except Exception as exc:
        print(f"cognee wipe skipped ({type(exc).__name__}: {exc})")
    for name in ("registry.json", "changelog.jsonl"):
        p = memory.DATA_DIR / name
        if p.exists():
            p.unlink()
            print(f"removed {p}")
    print("reset complete")


if __name__ == "__main__":
    asyncio.run(main())
