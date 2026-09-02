from __future__ import annotations

import functools
import http.server
import os
import socketserver
import threading
from typing import Optional


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass


class BenchmarkServer:
    def __init__(self, root: str, port: int = 0):
        self.root = os.path.abspath(root)
        self.port = port
        self._httpd: Optional[socketserver.TCPServer] = None
        self._thread: Optional[threading.Thread] = None

    def __enter__(self) -> "BenchmarkServer":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    def start(self) -> None:
        handler = functools.partial(_QuietHandler, directory=self.root)
        socketserver.TCPServer.allow_reuse_address = True
        self._httpd = socketserver.TCPServer(("127.0.0.1", self.port), handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def url_for(self, app_file: str) -> str:
        return "http://127.0.0.1:{0}/{1}".format(self.port, app_file)
