"""HTTP server with web setup UI + healthcheck — no dependencies beyond stdlib."""
import json
import os
import socket
import sys
import time
from urllib.parse import parse_qs, urlparse

from web_setup import handle_web_setup

PORT = int(os.environ.get("PORT", 7860))

ROUTES = {
    "/": b"ok",
    "/health": b"ok",
}


def serve():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", PORT))
    s.listen(5)
    s.settimeout(1.0)
    print(f"[http] Listening on {PORT}", flush=True)
    while True:
        try:
            conn, _ = s.accept()
            data = conn.recv(65536)
            if not data:
                conn.close()
                continue

            raw = data.decode("utf-8", errors="replace")
            request_line, rest = raw.split("\r\n", 1)
            parts = request_line.split(" ")
            method = parts[0] if len(parts) > 0 else "GET"
            full_path = parts[1] if len(parts) > 1 else "/"

            parsed = urlparse(full_path)
            path = parsed.path
            query = parse_qs(parsed.query)

            # Read body if present
            body_bytes = b""
            if "\r\n\r\n" in raw:
                body_bytes = raw.split("\r\n\r\n", 1)[1].encode("utf-8")

            # Try web_setup handler first
            if path.startswith("/setup"):
                status, body, content_type = handle_web_setup(method, path, body_bytes, query)
            else:
                static = ROUTES.get(path)
                if static is not None:
                    status, body, content_type = 200, static, "text/plain"
                else:
                    # fallback: serve the setup page
                    status, body, content_type = handle_web_setup("GET", "/setup", b"", query)

            resp = (
                f"HTTP/1.1 {status} {'OK' if status == 200 else 'Redirect'}\r\n"
                f"Content-Type: {content_type}\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"Connection: close\r\n"
                f"\r\n"
            ).encode() + (body if isinstance(body, bytes) else body.encode())
            conn.sendall(resp)
            conn.close()
        except socket.timeout:
            continue
        except Exception as e:
            print(f"[http] Error: {e}", flush=True)
            try:
                conn.close()
            except Exception:
                pass


# Fork so child runs HTTP server, parent runs the bot
pid = os.fork()
if pid == 0:
    serve()
    sys.exit(0)

print(f"[http] Child PID={pid} serving HTTP", flush=True)
time.sleep(0.5)

# Now start the bot
try:
    import bot.__main__  # noqa: F401
except SystemExit:
    print("[http] Bot config missing", flush=True)
except Exception as e:
    print(f"[http] Bot error: {e}", flush=True)
    import traceback
    traceback.print_exc()

while True:
    time.sleep(60)
