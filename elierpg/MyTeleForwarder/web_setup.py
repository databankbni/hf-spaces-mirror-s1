import asyncio
import html
import json
import logging
import os
import secrets
import re
import sys

from pyrogram import Client
from pyrogram.errors import (
    FloodWait,
    SessionPasswordNeeded,
    PhoneCodeInvalid,
    PhoneCodeExpired,
)

from bot import API_ID, API_HASH

# ─── Session storage for web setup flow ──────────────
_setup_sessions = {}  # {session_id: {"temp": Client, "phone": str, "phone_hash": str, "step": str}}


def _ensure_loop():
    """Make sure the current thread has an asyncio event loop."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


def cleanup_session(sid):
    session = _setup_sessions.pop(sid, None)
    if session:
        try:
            session["temp"].disconnect()
        except Exception:
            pass


def handle_web_setup(method, path, body_bytes, query_params):
    """Handle web-based setup requests. Returns (status_code, body_bytes, content_type)."""

    # ── GET /setup or GET /setup?sid=... ──────────────────
    if method == "GET" and path == "/setup":
        # If SESSION_STRING is already set, show "already configured" page
        if os.environ.get("SESSION_STRING"):
            return _render_already_done()

        sid = query_params.get("sid", [None])[0]
        if sid and sid in _setup_sessions:
            session = _setup_sessions[sid]
            step = session.get("step", "phone")
            if step == "phone":
                return _render_setup_phone(sid, None)
            elif step == "code":
                return _render_setup_code(sid, None)
            elif step == "2fa":
                return _render_setup_2fa(sid, None)
        return _render_setup_phone(None, None)

    # ── POST /setup (send phone) ──────────────────────────
    if method == "POST" and path == "/setup":
        try:
            data = json.loads(body_bytes) if body_bytes else {}
        except json.JSONDecodeError:
            data = {}
        phone = (data.get("phone") or "").strip()
        if not phone:
            return _render_setup_phone(None, "Ingresa tu número de teléfono.")

        sid = secrets.token_hex(8)
        try:
            _ensure_loop()
            temp = Client(
                f":memory:{sid}", api_id=API_ID, api_hash=API_HASH, in_memory=True,
                device_model="Desktop", app_version="1.0.0", system_version="Linux",
            )
            temp.connect()
            sent = temp.send_code(phone)
            _setup_sessions[sid] = {
                "temp": temp,
                "phone": phone,
                "phone_hash": sent.phone_code_hash,
                "step": "code",
            }
            logging.getLogger("web_setup").info(f"Session {sid}: code sent to {phone}")
            return _render_setup_code(sid, None)
        except FloodWait as exc:
            m = re.search(r"wait of (\d+) seconds", str(exc))
            wait = m.group(1) if m else "60"
            return _render_setup_phone(None, f"Demasiados intentos. Espera {wait} segundos.")
        except Exception as e:
            logging.getLogger("web_setup").error(f"Send code error: {e}")
            return _render_setup_phone(None, f"Error: {e}")

    # ── POST /setup/verify (send code) ────────────────────
    if method == "POST" and path == "/setup/verify":
        try:
            data = json.loads(body_bytes) if body_bytes else {}
        except json.JSONDecodeError:
            data = {}
        sid = data.get("sid", "")
        code = (data.get("code") or "").strip()
        if not sid or sid not in _setup_sessions:
            return _render_setup_phone(None, "Sesión expirada. Empieza de nuevo.")
        if not code:
            return _render_setup_code(sid, "Ingresa el código.")

        session = _setup_sessions[sid]
        temp = session["temp"]
        phone = session["phone"]
        phone_hash = session["phone_hash"]

        try:
            temp.sign_in(phone, phone_hash, code)
            session_string = temp.export_session_string()
            temp.disconnect()
            cleanup_session(sid)
            return _render_result(session_string)
        except SessionPasswordNeeded:
            session["step"] = "2fa"
            return _render_setup_2fa(sid, None)
        except PhoneCodeInvalid:
            return _render_setup_code(sid, "Código incorrecto. Revisa Telegram e intenta de nuevo.")
        except PhoneCodeExpired:
            cleanup_session(sid)
            return _render_setup_phone(None, "El código expiró. Empieza de nuevo.")
        except FloodWait as exc:
            m = re.search(r"wait of (\d+) seconds", str(exc))
            wait = m.group(1) if m else "60"
            return _render_setup_code(sid, f"Demasiados intentos. Espera {wait}s y usa /setup de nuevo.")
        except Exception as e:
            err_str = str(e)
            if "PHONE_CODE_INVALID" in err_str or "code" in err_str.lower():
                return _render_setup_code(
                    sid,
                    "Código incorrecto o bloqueado por seguridad. "
                    "Revisa Telegram en tu teléfono — puede que haya llegado "
                    "un mensaje con botón **Aprobar**. "
                    "Presiónalo y luego intenta de nuevo."
                )
            cleanup_session(sid)
            return _render_setup_phone(None, f"Error: {e}")

    # ── POST /setup/2fa (send 2FA password) ───────────────
    if method == "POST" and path == "/setup/2fa":
        try:
            data = json.loads(body_bytes) if body_bytes else {}
        except json.JSONDecodeError:
            data = {}
        sid = data.get("sid", "")
        password = (data.get("password") or "").strip()
        if not sid or sid not in _setup_sessions:
            return _render_setup_phone(None, "Sesión expirada. Empieza de nuevo.")
        if not password:
            return _render_setup_2fa(sid, "Ingresa tu contraseña.")

        session = _setup_sessions[sid]
        temp = session["temp"]

        try:
            temp.check_password(password)
            session_string = temp.export_session_string()
            temp.disconnect()
            cleanup_session(sid)
            return _render_result(session_string)
        except Exception as e:
            return _render_setup_2fa(sid, f"Contraseña incorrecta. Intenta de nuevo.")

    return (404, b"Not found", "text/plain")


# ─── HTML renderers ──────────────────────────────────

def _page(title, body):
    return (200, f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #f5f5f5; display: flex; justify-content: center;
    align-items: center; min-height: 100vh; padding: 20px;
  }}
  .card {{
    background: white; border-radius: 12px; padding: 32px;
    max-width: 480px; width: 100%; box-shadow: 0 2px 12px rgba(0,0,0,0.08);
  }}
  h1 {{ font-size: 22px; margin-bottom: 8px; color: #1a1a1a; }}
  p {{ color: #666; margin-bottom: 20px; font-size: 14px; line-height: 1.5; }}
  label {{ display: block; font-size: 13px; font-weight: 600; margin-bottom: 4px; color: #333; }}
  input[type=text], input[type=password] {{
    width: 100%; padding: 10px 12px; border: 1px solid #ddd; border-radius: 8px;
    font-size: 16px; margin-bottom: 16px;
  }}
  input[type=text]:focus, input[type=password]:focus {{ outline: none; border-color: #2481cc; }}
  button {{
    background: #2481cc; color: white; border: none; border-radius: 8px;
    padding: 12px; font-size: 16px; cursor: pointer; width: 100%; font-weight: 600;
  }}
  button:hover {{ background: #1a6bb5; }}
  .error {{ background: #fef2f2; color: #b91c1c; padding: 10px; border-radius: 8px; margin-bottom: 16px; font-size: 14px; }}
  .result {{ background: #f0fdf4; color: #15803d; padding: 12px; border-radius: 8px; margin-bottom: 16px; word-break: break-all; font-family: monospace; font-size: 13px; }}
  .hint {{ font-size: 12px; color: #999; margin-top: -12px; margin-bottom: 16px; }}
  .emoji {{ font-size: 32px; margin-bottom: 8px; }}
</style>
</head>
<body>
<div class="card">
{body}
</div>
</body>
</html>""".encode(), "text/html")


def _render_setup_phone(sid, error):
    err_block = f'<div class="error">{html.escape(error)}</div>' if error else ""
    body = f"""
<div class="emoji">📱</div>
<h1>Obtener SESSION_STRING</h1>
<p>Ingresa tu número de teléfono en formato internacional. Se te enviará un código de verificación por Telegram.</p>
{err_block}
<form action="#" onsubmit="submitPhone(event)">
<label for="phone">Número de teléfono</label>
<input type="text" id="phone" name="phone" placeholder="+34123456789" value="+" required>
<div class="hint">Incluye el código de país (ej: +34 para España)</div>
<button type="submit">Enviar código</button>
</form>
<div id="loading" style="display:none;text-align:center;padding:20px;color:#666;">⏳ Enviando código, espera...</div>
<script>
async function submitPhone(e) {{
  e.preventDefault();
  document.getElementById('loading').style.display = 'block';
  const phone = document.getElementById('phone').value;
  const resp = await fetch('/setup', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{phone}})
  }});
  const html = await resp.text();
  document.open(); document.write(html); document.close();
}}
</script>
"""
    return _page("Setup - Telegram Forwarder", body)


def _render_setup_code(sid, error):
    err_block = f'<div class="error">{html.escape(error)}</div>' if error else ""
    body = f"""
<div class="emoji">🔑</div>
<h1>Verificación</h1>
<p>Te llegó un código a Telegram. Ingresa los 5 dígitos.</p>
{err_block}
<form action="#" onsubmit="submitCode(event)">
<input type="hidden" name="sid" value="{html.escape(sid)}">
<label for="code">Código de verificación</label>
<input type="text" id="code" name="code" placeholder="12345" required>
<button type="submit">Verificar código</button>
</form>
<script>
async function submitCode(e) {{
  e.preventDefault();
  const code = document.getElementById('code').value;
  const resp = await fetch('/setup/verify', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{sid: '{html.escape(sid)}', code}})
  }});
  const html = await resp.text();
  document.open(); document.write(html); document.close();
}}
</script>
"""
    return _page("Setup - Telegram Forwarder", body)


def _render_setup_2fa(sid, error):
    err_block = f'<div class="error">{html.escape(error)}</div>' if error else ""
    body = f"""
<div class="emoji">🔐</div>
<h1>Verificación en dos pasos</h1>
<p>Tienes 2FA activado. Ingresa tu contraseña de Telegram.</p>
{err_block}
<form action="#" onsubmit="submit2fa(event)">
<input type="hidden" name="sid" value="{html.escape(sid)}">
<label for="password">Contraseña 2FA</label>
<input type="password" id="password" name="password" placeholder="Tu contraseña" required>
<button type="submit">Verificar</button>
</form>
<script>
async function submit2fa(e) {{
  e.preventDefault();
  const password = document.getElementById('password').value;
  const resp = await fetch('/setup/2fa', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{sid: '{html.escape(sid)}', password}})
  }});
  const html = await resp.text();
  document.open(); document.write(html); document.close();
}}
</script>
"""
    return _page("Setup - Telegram Forwarder", body)


def _render_result(session_string):
    body = f"""
<div class="emoji">✅</div>
<h1>¡Listo!</h1>
<p>Copia esta SESSION_STRING y pégala en los <strong>Secrets</strong> de HuggingFace como variable <code>SESSION_STRING</code>.</p>
<div class="result">{html.escape(session_string)}</div>
<p style="font-size:13px;color:#666;">Luego reinicia el Space desde el Dashboard de HF.<br>
Mientras tanto, el bot sigue funcionando con el BOT_TOKEN.</p>
<a href="/setup" style="display:block;text-align:center;margin-top:16px;color:#2481cc;">🔄 Otra cuenta</a>
"""
    return _page("Setup - Telegram Forwarder", body)


def _render_already_done():
    body = """
<div class="emoji">✅</div>
<h1>SESSION_STRING ya configurada</h1>
<p>Ya tienes una SESSION_STRING en los Secrets de HuggingFace.<br>
El bot está funcionando en modo <strong>Usuario</strong>.</p>
<p style="font-size:13px;color:#666;">
Si quieres cambiarla, ve a HF Settings → Secrets y actualiza <code>SESSION_STRING</code>,
luego reinicia el Space.
</p>
<a href="/" style="display:block;text-align:center;margin-top:16px;color:#2481cc;">Volver</a>
"""
    return _page("Setup - Telegram Forwarder", body)
