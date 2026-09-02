from __future__ import annotations

from typing import Any, Dict, List, Optional

from .models import Action
from .oracle import CrashOracle, DomOracle, VisualOracle
from .server import BenchmarkServer

PASS, FAIL = "  [ok]  ", "  [fail]"


def _ref_by(elements: List[Dict[str, Any]], **match) -> Optional[int]:
    for el in elements:
        if all(str(el.get(k, "")) == v for k, v in match.items()):
            return el["ref"]
    return None


def _ref_by_text(elements: List[Dict[str, Any]], text: str) -> Optional[int]:
    for el in elements:
        if text.lower() in (el.get("text") or "").lower() and el.get("clickable"):
            return el["ref"]
    return None


def run_smoke(apps_dir: str = "benchmark/apps", headless: bool = True) -> int:
    from .driver.web import WebDriver

    checks: List[bool] = []

    def check(ok: bool, label: str, detail: str = "") -> None:
        checks.append(bool(ok))
        print("{0} {1}{2}".format(PASS if ok else FAIL, label,
                                  ("  <- " + detail) if detail else ""))

    with BenchmarkServer(apps_dir) as server:
        crash = CrashOracle()
        d = WebDriver(crash, {"width": 900, "height": 700}, headless=headless)
        try:
            d.start()
            d.goto(server.url_for("todo-crash.html"))
            snap, shot = d.snapshot()
            els = snap["elements"]
            check(len(els) > 3, "perception sees the page", "{0} elements".format(len(els)))
            check(len(shot) > 1000, "screenshot captured", "{0} bytes".format(len(shot)))
            ref = _ref_by(els, testid="delete-1")
            check(ref is not None, "element addressing by test id")
            if ref is not None:
                result, frames, stamps = d.act_with_burst(Action("click", {"ref": ref}))
                check(result == "ok", "click executed", result)
                sigs = crash.drain(0)
                check(any(s.kind == "page_error" for s in sigs),
                      "crash oracle catches the seeded TypeError",
                      "; ".join(s.kind for s in sigs) or "no signals")
        except Exception as exc:
            check(False, "todo-crash driver run", "{0}: {1}".format(type(exc).__name__, exc))
        finally:
            d.stop()

        crash = CrashOracle()
        d = WebDriver(crash, {"width": 900, "height": 700}, headless=headless)
        try:
            d.start()
            d.goto(server.url_for("drawer-jank.html"))
            snap, _ = d.snapshot()
            ref = _ref_by_text(snap["elements"], "Open menu")
            check(ref is not None, "found the drawer toggle")
            if ref is not None:
                _, frames, stamps = d.act_with_burst(Action("click", {"ref": ref}))
                sigs = VisualOracle().inspect(0, frames, stamps)
                kinds = {s.kind for s in sigs}
                check(len(frames) >= 8, "frame burst captured", "{0} frames".format(len(frames)))
                check("stepped_animation" in kinds or "capture_stall" in kinds,
                      "visual oracle flags the janky drawer",
                      ", ".join(sorted(kinds)) or "no signals")
        except Exception as exc:
            check(False, "drawer-jank driver run", "{0}: {1}".format(type(exc).__name__, exc))
        finally:
            d.stop()

        crash = CrashOracle()
        d = WebDriver(crash, {"width": 900, "height": 700}, headless=headless)
        try:
            d.start()
            d.goto(server.url_for("modal-close.html"))
            snap, _ = d.snapshot()
            ref = _ref_by_text(snap["elements"], "Open settings")
            if ref is not None:
                d.act(Action("click", {"ref": ref}))
            snap, _ = d.snapshot()
            before = snap["elements"]
            x_ref = _ref_by(before, id="closeX")
            check(x_ref is not None, "modal opened and the X button is visible")
            if x_ref is not None:
                _, frames, stamps = d.act_with_burst(Action("click", {"ref": x_ref}))
                snap2, _ = d.snapshot()
                vis = {s.kind for s in VisualOracle().inspect(1, frames, stamps)}
                dom = {s.kind for s in DomOracle().inspect(1, before, snap2["elements"], snap2.get("viewport"))}
                check("no_op" in vis or "no_dom_change" in dom,
                      "the dead X button is detected as a no-op",
                      "visual: {0} | dom: {1}".format(", ".join(sorted(vis)) or "none",
                                                      ", ".join(sorted(dom)) or "none"))

            d.goto(server.url_for("header-overlap.html"))
            d.act(Action("resize", {"width": 520, "height": 720}))
            snap, _ = d.snapshot()
            dom_sigs = DomOracle().inspect(2, None, snap["elements"], snap.get("viewport"))
            check(any(s.kind == "overlap" for s in dom_sigs),
                  "dom oracle detects the pinned bar covering content",
                  "; ".join(s.detail for s in dom_sigs if s.kind == "overlap") or "no overlap found")
        except Exception as exc:
            check(False, "modal/overlap driver run", "{0}: {1}".format(type(exc).__name__, exc))
        finally:
            d.stop()

    ok = sum(1 for c in checks if c)
    print("\n{0}/{1} checks passed".format(ok, len(checks)))
    if ok != len(checks):
        print("The harness is not fully working on this machine. Fix these before spending "
              "tokens on a real run.")
    return 0 if ok == len(checks) else 1
