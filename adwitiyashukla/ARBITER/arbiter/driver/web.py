from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..models import Action
from ..perception import COLLECT_JS, MAX_ELEMENTS
from .base import Driver

ACTION_TIMEOUT_MS = 3000
BURST_FRAMES = 12
BURST_INTERVAL_MS = 80


def _decode_gray(buf: bytes) -> Optional[np.ndarray]:
    try:
        import cv2
        arr = np.frombuffer(buf, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    except Exception:
        return None


class WebDriver(Driver):
    name = "web"

    def __init__(self, crash_oracle, viewport: Dict[str, int], headless: bool = True,
                 video_dir: str = "", slow_mo: int = 0):
        self.crash = crash_oracle
        self.viewport = {"width": int(viewport.get("width", 1000)),
                         "height": int(viewport.get("height", 800))}
        self.headless = headless
        self.video_dir = video_dir
        self.slow_mo = slow_mo
        self._pw = None
        self._browser = None
        self._ctx = None
        self.page = None

    def start(self) -> None:
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless, slow_mo=self.slow_mo)
        kwargs: Dict[str, Any] = {"viewport": dict(self.viewport)}
        if self.video_dir:
            os.makedirs(self.video_dir, exist_ok=True)
            kwargs["record_video_dir"] = self.video_dir
            kwargs["record_video_size"] = dict(self.viewport)
        self._ctx = self._browser.new_context(**kwargs)
        self.page = self._ctx.new_page()
        self.page.set_default_timeout(ACTION_TIMEOUT_MS)

        self.page.on("pageerror", lambda err: self.crash.on_page_error(str(err)))
        self.page.on("console", lambda msg: self.crash.on_console(msg.type, msg.text))
        self.page.on("requestfailed",
                     lambda req: self.crash.on_request_failed(req.url, str(req.failure)))
        self.page.on("response", lambda res: self.crash.on_response(res.url, res.status))
        self.page.on("dialog", lambda d: d.accept())

    def stop(self) -> str:
        video_path = ""
        try:
            if self._ctx:
                self._ctx.close()
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        if self.video_dir and os.path.isdir(self.video_dir):
            webm = sorted(f for f in os.listdir(self.video_dir) if f.endswith(".webm"))
            video_path = os.path.join(self.video_dir, webm[0]) if webm else ""
        return video_path

    @property
    def url(self) -> str:
        return self.page.url if self.page else ""

    def goto(self, url: str) -> None:
        self.page.goto(url, wait_until="load", timeout=15000)

    def snapshot(self) -> Tuple[Dict[str, Any], bytes]:
        data = self.page.evaluate(COLLECT_JS, MAX_ELEMENTS)
        shot = self.page.screenshot(type="png")
        return data, shot

    def frame(self) -> Optional[np.ndarray]:
        try:
            return _decode_gray(self.page.screenshot(type="jpeg", quality=55))
        except Exception:
            return None

    def _sel(self, ref: int) -> str:
        return '[data-arbiter-ref="{0}"]'.format(int(ref))

    def act(self, action: Action) -> str:
        from playwright.sync_api import Error as PWError
        a, args = action.name, action.args
        try:
            if a == "click":
                self.page.click(self._sel(args["ref"]))
            elif a == "double_click":
                self.page.dblclick(self._sel(args["ref"]))
            elif a == "click_at":
                self.page.mouse.click(args["x"], args["y"])
            elif a == "type":
                sel = self._sel(args["ref"])
                if args.get("clear"):
                    self.page.fill(sel, "")
                self.page.click(sel)
                self.page.type(sel, str(args["text"]), delay=25)
            elif a == "press_key":
                self.page.keyboard.press(str(args["key"]))
            elif a == "hover":
                self.page.hover(self._sel(args["ref"]))
            elif a == "select_option":
                self.page.select_option(self._sel(args["ref"]), str(args["value"]))
            elif a == "check":
                self.page.click(self._sel(args["ref"]))
            elif a == "drag":
                self.page.drag_and_drop(self._sel(args["ref"]), self._sel(args["to_ref"]))
            elif a == "scroll":
                amount = int(args.get("amount", 400))
                self.page.mouse.wheel(0, amount if str(args["direction"]).lower() == "down" else -amount)
            elif a == "resize":
                self.viewport = {"width": args["width"], "height": args["height"]}
                self.page.set_viewport_size(dict(self.viewport))
            elif a == "wait":
                self.page.wait_for_timeout(args["ms"])
            elif a == "go_back":
                self.page.go_back()
            elif a == "reload":
                self.page.reload()
            elif a == "finish":
                return "run ended by the actor"
            else:
                return "unsupported action {0}".format(a)
            return "ok"
        except PWError as exc:
            first = str(exc).strip().splitlines()[0]
            return "failed: {0}".format(first[:220])
        except Exception as exc:
            return "failed: {0}: {1}".format(type(exc).__name__, str(exc)[:200])

    def act_with_burst(self, action: Action, frames: int = BURST_FRAMES,
                       interval_ms: int = BURST_INTERVAL_MS
                       ) -> Tuple[str, List[np.ndarray], List[float]]:
        shots: List[np.ndarray] = []
        stamps: List[float] = []

        def grab() -> None:
            f = self.frame()
            if f is not None:
                shots.append(f)
                stamps.append(time.perf_counter() * 1000.0)

        grab()
        result = self.act(action)
        for _ in range(max(0, frames - 1)):
            t0 = time.perf_counter()
            grab()
            spent = (time.perf_counter() - t0) * 1000.0
            remaining = interval_ms - spent
            if remaining > 0:
                time.sleep(remaining / 1000.0)
        return result, shots, stamps
