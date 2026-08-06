import os
import socket
import sys
import threading
import time
from pathlib import Path

import webview

from app import _configure_tesseract, app


def _base_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def _pick_port(start_port: int = 7860, tries: int = 20) -> int:
    for port in range(start_port, start_port + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("Could not find a free local port for the desktop app.")


def _wait_for_server(port: int, timeout_seconds: float = 20.0) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _run_server(port: int) -> None:
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True)


class DesktopBridge:
    def close_app(self) -> bool:
        def _close() -> None:
            try:
                if webview.windows:
                    webview.windows[0].destroy()
            except Exception:
                pass

        threading.Thread(target=_close, daemon=True).start()
        return True

    def restart_app(self) -> bool:
        def _restart() -> None:
            try:
                if webview.windows:
                    webview.windows[0].destroy()
            except Exception:
                pass
            time.sleep(0.2)
            os.execv(sys.executable, [sys.executable] + sys.argv)

        threading.Thread(target=_restart, daemon=True).start()
        return True


def main() -> None:
    root = _base_dir()
    os.chdir(root)

    _configure_tesseract()

    port = _pick_port(7860, 20)
    server_thread = threading.Thread(target=_run_server, args=(port,), daemon=True)
    server_thread.start()

    if not _wait_for_server(port):
        raise RuntimeError("Local OCR server failed to start.")

    bridge = DesktopBridge()
    window = webview.create_window(
        "Portable OCR Studio",
        url=f"http://127.0.0.1:{port}",
        width=1360,
        height=900,
        min_size=(1040, 680),
        resizable=True,
        js_api=bridge,
    )
    webview.start()


if __name__ == "__main__":
    main()
