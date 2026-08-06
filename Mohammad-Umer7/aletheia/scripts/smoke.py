"""Phase 1 gate: exercise the full memory lifecycle end to end, printing everything.

reset -> remember (one permanent fact + one session fact) -> recall both ->
improve (bridge session s1 into the permanent graph) -> recall again ->
forget the dataset -> recall returns nothing relevant.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import memory

DS = "smoke_patient_zero"
PERMANENT_FACT = (
    "Field notes, Aurora Station, 2024: The bioluminescent coastal moss Bryum lumina "
    "glows a faint blue at night. Researcher Dr. Lyra Voss documented that its glow "
    "intensity doubles after rainfall."
)
SESSION_FACT = (
    "Session observation: On the night of June 12th, Dr. Voss noted that the Bryum lumina "
    "colony near the tide pools glowed green instead of blue — the only green glow ever recorded."
)
Q_PERMANENT = "What is unusual about the moss Bryum lumina, and who studies it?"
Q_SESSION = "Did Bryum lumina ever glow a color other than blue?"


def show(label: str, results: list) -> None:
    print(f"\n--- {label} ---")
    if not results:
        print("(no results)")
    for i, r in enumerate(results, 1):
        print(f"[{i}] {r}")


async def main() -> None:
    print("=== SMOKE 1/8: reset (forget everything) ===")
    try:
        print(f"reset ok: {await memory.forget_everything()}")
    except Exception as exc:
        print(f"reset: nothing to forget yet ({type(exc).__name__}: {exc})")

    print("\n=== SMOKE 2/8: remember permanent fact ===")
    print(await memory.remember(PERMANENT_FACT, DS))

    print("\n=== SMOKE 3/8: remember session fact (session_id='s1') ===")
    print(await memory.remember(SESSION_FACT, DS, session_id="s1"))

    print("\n=== SMOKE 4/8: recall both ===")
    show("recall permanent", await memory.recall(Q_PERMANENT, [DS]))
    show("recall session (session_id='s1')", await memory.recall(Q_SESSION, [DS], session_id="s1"))

    # Learn the true shape of recall entries once, for the normalizer + attribution.
    raw = await memory.recall_raw(Q_PERMANENT, [DS])
    if raw:
        print(f"\n[shape] first recall entry type: {type(raw[0]).__name__}")
        print(f"[shape] repr (truncated): {repr(raw[0])[:600]}")

    print("\n=== SMOKE 5/8: improve (bridge session s1 into permanent graph) ===")
    print(await memory.improve(DS, session_ids=["s1"]))

    print("\n=== SMOKE 6/8: recall after improve ===")
    show("recall permanent after improve", await memory.recall(Q_PERMANENT, [DS]))
    show("recall session fact WITHOUT session_id after improve", await memory.recall(Q_SESSION, [DS]))

    print("\n=== SMOKE 7/8: forget the dataset ===")
    print(await memory.forget_dataset(DS))

    print("\n=== SMOKE 8/8: recall after forget (expect nothing relevant) ===")
    try:
        show("recall after forget", await memory.recall(Q_PERMANENT, [DS]))
    except Exception as exc:
        print(f"recall raised {type(exc).__name__}: {exc}")
        print("(dataset is gone -> error instead of empty result; acceptable)")

    print("\nSMOKE COMPLETE")


if __name__ == "__main__":
    asyncio.run(main())
