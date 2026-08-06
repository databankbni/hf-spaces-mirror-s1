#!/usr/bin/env python3
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PUBLIC_PORT = int(os.environ.get("PORT", 7860))
RASA_PORT = 5005
ACTIONS_PORT = 5055

state = {
    "rasa_ready": False,
    "actions_ready": False,
    "rasa_exit_code": None,
    "actions_exit_code": None,
    "started_at": time.time(),
}


def rasa_base_url():
    return f"http://127.0.0.1:{RASA_PORT}"


def actions_base_url():
    return f"http://127.0.0.1:{ACTIONS_PORT}"


def status_payload():
    uptime_seconds = int(time.time() - state["started_at"])
    if state["rasa_ready"] and state["actions_ready"]:
        return 200, {
            "status": "ready",
            "uptime_seconds": uptime_seconds,
            "rasa_ready": True,
            "actions_ready": True,
        }
    if state["rasa_exit_code"] is not None or state["actions_exit_code"] is not None:
        return 500, {
            "status": "crashed",
            "uptime_seconds": uptime_seconds,
            "rasa_exit_code": state["rasa_exit_code"],
            "actions_exit_code": state["actions_exit_code"],
            "rasa_ready": state["rasa_ready"],
            "actions_ready": state["actions_ready"],
        }
    return 503, {
        "status": "loading",
        "uptime_seconds": uptime_seconds,
        "rasa_ready": state["rasa_ready"],
        "actions_ready": state["actions_ready"],
    }


def wait_until_actions_ready():
    while state["actions_exit_code"] is None and not state["actions_ready"]:
        try:
            with socket.create_connection(("127.0.0.1", ACTIONS_PORT), timeout=2):
                state["actions_ready"] = True
                return
        except Exception:
            time.sleep(1)
            continue


def wait_until_rasa_ready():
    probe_url = f"{rasa_base_url()}/status"
    while state["rasa_exit_code"] is None and not state["rasa_ready"]:
        try:
            with urllib.request.urlopen(probe_url, timeout=2) as response:
                if 200 <= response.status < 300:
                    state["rasa_ready"] = True
                    return
        except Exception:
            time.sleep(2)


class ProxyHandler(BaseHTTPRequestHandler):
    def _write_json(self, status_code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _proxy(self, method):
        if self.path in ("/", "/health", "/healthz"):
            _, payload = status_payload()
            self._write_json(200, payload)
            return

        if self.path == "/status":
            status_code, payload = status_payload()
            self._write_json(status_code, payload)
            return

        if not (state["rasa_ready"] and state["actions_ready"]):
            status_code, payload = status_payload()
            self._write_json(status_code, payload)
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length else None
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in ("host", "content-length", "transfer-encoding")
        }
        request = urllib.request.Request(
            f"{rasa_base_url()}{self.path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                response_body = response.read()
                self.send_response(response.status)
                for key, value in response.headers.items():
                    if key.lower() != "transfer-encoding":
                        self.send_header(key, value)
                self.end_headers()
                self.wfile.write(response_body)
        except urllib.error.HTTPError as exc:
            response_body = exc.read()
            self.send_response(exc.code)
            for key, value in exc.headers.items():
                if key.lower() != "transfer-encoding":
                    self.send_header(key, value)
            self.end_headers()
            self.wfile.write(response_body)
        except Exception:
            status_code, payload = status_payload()
            self._write_json(status_code, payload)

    def do_GET(self):
        self._proxy("GET")

    def do_POST(self):
        self._proxy("POST")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


def start_actions():
    process = subprocess.Popen(
        [sys.executable, "-m", "rasa_sdk", "--actions", "actions", "--port", str(ACTIONS_PORT)]
    )
    threading.Thread(target=wait_until_actions_ready, daemon=True).start()
    state["actions_exit_code"] = process.wait()
    state["actions_ready"] = False


def start_rasa():
    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as handle:
        handle.write(
            'action_endpoint:\n  url: "http://127.0.0.1:%s/webhook"\n' % ACTIONS_PORT
        )
        endpoints_path = handle.name

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "rasa",
            "run",
            "--enable-api",
            "--interface",
            "0.0.0.0",
            "--port",
            str(RASA_PORT),
            "--credentials",
            "credentials.yml",
            "--endpoints",
            endpoints_path,
            "--model",
            "models",
            "--cors",
            "*",
        ]
    )
    threading.Thread(target=wait_until_rasa_ready, daemon=True).start()
    state["rasa_exit_code"] = process.wait()
    state["rasa_ready"] = False


if __name__ == "__main__":
    threading.Thread(target=start_actions, daemon=True).start()
    threading.Thread(target=start_rasa, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", PUBLIC_PORT), ProxyHandler)
    print(f"Proxy haibot activo en :{PUBLIC_PORT} -> rasa:{RASA_PORT}, actions:{ACTIONS_PORT}", flush=True)
    server.serve_forever()
