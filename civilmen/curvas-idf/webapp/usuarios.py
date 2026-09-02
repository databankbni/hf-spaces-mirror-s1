"""Usuarios, verificación por correo y cupo de ejecuciones — webapp HYDROFRA.

Modelo:
- **Login con verificación por correo**: el usuario ingresa su correo, recibe
  un código de 6 dígitos por email (OTP) y lo confirma. Solo un correo
  verificado puede ejecutar la app. Esto endurece la barrera frente al uso con
  correos falsos.
- **Cupo de 3 ejecuciones por usuario (total, sin reinicio mensual)**. Al
  agotarlo, para seguir usando la app el usuario debe comunicarse con el
  administrador y adquirir una **licencia mensual** (costo único de Bs 500).
- **Licencia**: el administrador activa una licencia mensual para un correo
  (30 días por defecto); mientras esté vigente, ese usuario ejecuta sin límite.

Durabilidad:
- Store JSON local (rápido) + **sincronización con el dataset de HuggingFace**
  (mismo repo y `HF_TOKEN` que la telemetría). Al cargar, descarga y fusiona el
  estado remoto (fuente de verdad ante reinicios del contenedor); ante cada
  cambio, sube el store en segundo plano. Si no hay `HF_TOKEN`, degrada a solo
  local.

Configurable por entorno:
- `HYDROFRA_LIMITE_ANALISIS` (defecto 3), `HYDROFRA_LICENCIA_DIAS` (30),
  `HYDROFRA_LICENCIA_COSTO_BS` (500), `HYDROFRA_USERS_FILE`,
  `HYDROFRA_HF_DATASET`, `HYDROFRA_ADMIN_TOKEN`.
- SMTP: `EMAIL_USERNAME`, `EMAIL_PASSWORD`, `EMAIL_SMTP_HOST`
  (defecto smtp.gmail.com), `EMAIL_SMTP_PORT` (465).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
import time
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

# ─────────────────── Configuración ───────────────────
LIMITE_GRATIS = int(os.environ.get("HYDROFRA_LIMITE_ANALISIS", "3"))
LICENCIA_DIAS = int(os.environ.get("HYDROFRA_LICENCIA_DIAS", "30"))
LICENCIA_COSTO_BS = os.environ.get("HYDROFRA_LICENCIA_COSTO_BS", "500")
# Verificación por correo OBLIGATORIA: si es True, nunca se omite el OTP (aunque
# no haya SMTP el usuario NO entra), garantizando que solo correos verificados
# accedan. Si es False, y no hay SMTP, se degrada permitiendo el acceso.
VERIFICACION_OBLIGATORIA = os.environ.get(
    "HYDROFRA_VERIFICACION_OBLIGATORIA", "").strip().lower() in (
    "1", "true", "si", "sí", "yes", "on")

_DIR = Path(os.environ.get("HYDROFRA_TELEMETRIA_DIR", "/tmp/idf-telemetria"))
_FILE = Path(os.environ.get("HYDROFRA_USERS_FILE", str(_DIR / "usuarios.json")))

_HF_REPO = os.environ.get("HYDROFRA_HF_DATASET", "civilmen/hydrofra-runs")
_HF_FILE = "usuarios.json"

_ADMIN_TOKEN = os.environ.get("HYDROFRA_ADMIN_TOKEN", "").strip()

_OTP_TTL_SEG = 600  # 10 minutos
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_LOCK = threading.RLock()
_DATA: dict = {}
_PENDIENTES: dict = {}   # email -> {"hash", "expira", "nombre"}

# Contacto del administrador / servicio (para adquirir la licencia).
CONTACTO = {
    "nombre": "Luis Franco Guarachi",
    "rol": "Administrador — Ingeniería Hidráulica Fluvial",
    "whatsapp": "+591 69907008",
    "whatsapp_url": "https://wa.me/59169907008",
    "descripcion": ("Estudios de hidráulica de ríos, puentes, socavación, "
                    "encauzamientos, vertederos y obras hidráulicas con "
                    "modelación 2D/3D e ingeniería estructural."),
}


# ─────────────────── Utilidades ───────────────────
def email_valido(email: str) -> bool:
    return bool(_EMAIL_RE.match((email or "").strip()))


def normalizar_email(email: str) -> str:
    return (email or "").strip().lower()


def _hoy() -> date:
    return datetime.now().date()


def _hash_codigo(email: str, codigo: str) -> str:
    return hashlib.sha256(f"{email}:{codigo}".encode()).hexdigest()


# ─────────────────── Persistencia local ───────────────────
def _cargar_archivo() -> dict:
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _guardar_archivo(data: dict) -> None:
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=0),
                   encoding="utf-8")
    tmp.replace(_FILE)


# ─────────────────── Persistencia HuggingFace ───────────────────
def _hf_api():
    try:
        from huggingface_hub import HfApi
    except Exception:  # noqa: BLE001
        return None, None
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if not token:
        return None, None
    return HfApi(token=token), token


def _descargar_hf() -> dict | None:
    api, token = _hf_api()
    if not api:
        return None
    try:
        from huggingface_hub import hf_hub_download
        p = hf_hub_download(repo_id=_HF_REPO, repo_type="dataset",
                            filename=_HF_FILE, token=token)
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _subir_hf(data: dict) -> None:
    api, token = _hf_api()
    if not api:
        return
    try:
        api.create_repo(repo_id=_HF_REPO, repo_type="dataset", exist_ok=True)
        api.upload_file(
            path_or_fileobj=json.dumps(data, ensure_ascii=False).encode("utf-8"),
            path_in_repo=_HF_FILE, repo_id=_HF_REPO, repo_type="dataset",
            commit_message="HYDROFRA: actualizar cupo/licencias de usuarios")
    except Exception:  # noqa: BLE001
        pass


def _subir_hf_async(data: dict) -> None:
    threading.Thread(target=_subir_hf, args=(dict(data),), daemon=True).start()


def _max_fecha(a, b):
    fechas = [x for x in (a, b) if x]
    return max(fechas) if fechas else None


def _merge(remoto: dict, local: dict) -> dict:
    """Fusiona conservadoramente: mayor conteo, verificado si alguno lo está,
    licencia con vencimiento más lejano. Evita que un reinicio 'regale' cupo.

    IMPORTANTE: la fusión parte de una COPIA del registro y solo sobrescribe
    los campos que realmente se reconcilian. La versión anterior reconstruía
    el registro desde cero con una lista fija de claves, de modo que cualquier
    campo no listado —en particular `password_hash`, y también `es_owner`— se
    PERDÍA en cuanto la cuenta existía a la vez en el remoto y en el local.
    El efecto práctico era que, tras el primer reinicio con persistencia
    activa, la cuenta sobrevivía pero se quedaba sin contraseña y el usuario
    no podía volver a entrar.
    """
    out = dict(remoto)
    for k, r in local.items():
        if k not in out:
            out[k] = r
            continue
        o = out[k]
        # Base: todos los campos del remoto, completados con los del local que
        # el remoto no tenga (así no se pierde nada en ninguna dirección).
        fusion = {**r, **{kk: vv for kk, vv in o.items() if vv is not None}}
        # La contraseña se conserva de donde exista; ante conflicto gana la más
        # reciente según `actualizado`.
        ph_o, ph_r = o.get("password_hash"), r.get("password_hash")
        if ph_o and ph_r and ph_o != ph_r:
            fusion["password_hash"] = (
                ph_o if _max_fecha(o.get("actualizado"),
                                   r.get("actualizado")) == o.get("actualizado")
                else ph_r)
        elif ph_o or ph_r:
            fusion["password_hash"] = ph_o or ph_r
        fusion.update({
            "nombre": r.get("nombre") or o.get("nombre") or "",
            "verificado": bool(o.get("verificado")) or bool(r.get("verificado")),
            "conteo": max(int(o.get("conteo", 0)), int(r.get("conteo", 0))),
            "licencia_hasta": _max_fecha(o.get("licencia_hasta"),
                                         r.get("licencia_hasta")),
            "creado": o.get("creado") or r.get("creado"),
            "actualizado": _max_fecha(o.get("actualizado"), r.get("actualizado")),
        })
        out[k] = fusion
    return out


def _sembrar_owner() -> None:
    """Siembra/refresca la cuenta del PROPIETARIO desde variables de entorno en
    cada arranque, para que el dueño SIEMPRE pueda ingresar aunque la
    persistencia (HF_TOKEN) no esté disponible y el contenedor se reinicie.

    Vars: HYDROFRA_OWNER_EMAIL, HYDROFRA_OWNER_PASSWORD (mín. 6),
    HYDROFRA_OWNER_NOMBRE (opcional). La cuenta queda verificada y con licencia
    de larga duración (acceso sin límite). No hace nada si faltan las vars.
    """
    email = normalizar_email(os.environ.get("HYDROFRA_OWNER_EMAIL", ""))
    pwd = os.environ.get("HYDROFRA_OWNER_PASSWORD", "")
    if not email or not _EMAIL_RE.match(email) or len(pwd) < 6:
        return
    nombre = (os.environ.get("HYDROFRA_OWNER_NOMBRE", "").strip()
              or CONTACTO.get("nombre", "Administrador"))
    r = _DATA.get(email) or {"conteo": 0,
                             "creado": datetime.now().isoformat(timespec="seconds")}
    r["nombre"] = r.get("nombre") or nombre
    r["verificado"] = True
    r["password_hash"] = _hash_password(pwd)
    # Licencia de larga duración (10 años) → acceso sin límite para el dueño.
    r["licencia_hasta"] = (_hoy() + timedelta(days=3650)).isoformat()
    r["es_owner"] = True
    r["actualizado"] = datetime.now().isoformat(timespec="seconds")
    _DATA[email] = r


def _inicializar() -> None:
    global _DATA
    with _LOCK:
        local = _cargar_archivo()
        remoto = _descargar_hf()
        _DATA = _merge(remoto or {}, local)
        _sembrar_owner()
        _guardar_archivo(_DATA)


def _persistir() -> None:
    _guardar_archivo(_DATA)
    _subir_hf_async(_DATA)


def _registro(email: str) -> dict:
    r = _DATA.get(email)
    if r is None:
        r = {"nombre": "", "verificado": False, "conteo": 0,
             "licencia_hasta": None,
             "creado": datetime.now().isoformat(timespec="seconds"),
             "actualizado": datetime.now().isoformat(timespec="seconds")}
        _DATA[email] = r
    return r


# ─────────────────── Licencia ───────────────────
def _licencia_activa(rec: dict) -> bool:
    lh = rec.get("licencia_hasta")
    if not lh:
        return False
    try:
        return date.fromisoformat(lh) >= _hoy()
    except Exception:  # noqa: BLE001
        return False


def otorgar_licencia(email: str, dias: int = None) -> dict:
    """Activa (o extiende) una licencia mensual para un correo. Uso admin."""
    dias = LICENCIA_DIAS if dias is None else int(dias)
    email = normalizar_email(email)
    with _LOCK:
        r = _registro(email)
        base = _hoy()
        if r.get("licencia_hasta"):
            try:
                actual = date.fromisoformat(r["licencia_hasta"])
                if actual > base:
                    base = actual   # extiende desde el vencimiento vigente
            except Exception:  # noqa: BLE001
                pass
        r["licencia_hasta"] = (base + timedelta(days=dias)).isoformat()
        r["verificado"] = True
        r["actualizado"] = datetime.now().isoformat(timespec="seconds")
        _persistir()
        return estado(email)


def admin_token_valido(token: str) -> bool:
    return bool(_ADMIN_TOKEN) and secrets.compare_digest(
        str(token or "").strip(), _ADMIN_TOKEN)


def admin_configurado() -> bool:
    return bool(_ADMIN_TOKEN)


def revocar_licencia(email: str) -> dict:
    """Quita la licencia de un correo (uso admin)."""
    email = normalizar_email(email)
    with _LOCK:
        r = _registro(email)
        r["licencia_hasta"] = None
        r["actualizado"] = datetime.now().isoformat(timespec="seconds")
        _persistir()
        return estado(email)


def listar() -> list[dict]:
    """Estado de todos los usuarios registrados (para el panel de admin)."""
    with _LOCK:
        emails = sorted(_DATA.keys())
    return [estado(e) for e in emails]


# ─────────────────── Verificación por correo (OTP) ───────────────────
# Nota: Hugging Face Spaces BLOQUEA el SMTP saliente (puertos 465/587). Por eso
# el envío se hace preferentemente por una API HTTP (puerto 443): Brevo, Resend
# o SendGrid. El SMTP queda como respaldo para despliegues que sí lo permitan.

_ASUNTO = "Tu código de acceso HYDROFRA"


def _cuerpo_email(codigo: str) -> str:
    return (f"Tu código de verificación HYDROFRA es: {codigo}\n\n"
            f"Ingresalo en la aplicación para continuar. Vence en 10 minutos.\n"
            f"Si no solicitaste este código, ignorá este correo.")


def _remitente() -> str:
    return (os.environ.get("EMAIL_FROM") or
            os.environ.get("EMAIL_USERNAME") or "")


def metodo_email() -> str | None:
    """Método de envío disponible, por prioridad: 'webhook' (relay HTTP propio,
    p. ej. Google Apps Script) | 'brevo' | 'resend' | 'sendgrid' | 'smtp' |
    None. 'webhook' no requiere remitente; los demás sí (EMAIL_FROM/EMAIL_USERNAME)."""
    if os.environ.get("EMAIL_WEBHOOK_URL"):
        return "webhook"
    if not _remitente():
        return None
    if os.environ.get("BREVO_API_KEY"):
        return "brevo"
    if os.environ.get("RESEND_API_KEY"):
        return "resend"
    if os.environ.get("SENDGRID_API_KEY"):
        return "sendgrid"
    if os.environ.get("EMAIL_PASSWORD"):
        return "smtp"
    return None


def smtp_configurado() -> bool:
    """True si hay ALGÚN método de correo configurado (HTTP o SMTP)."""
    return metodo_email() is not None


def _enviar_email_http(destino: str, codigo: str, metodo: str) -> bool:
    import json
    import urllib.error
    import urllib.request
    remitente = _remitente()
    texto = _cuerpo_email(codigo)
    if metodo == "brevo":
        url = "https://api.brevo.com/v3/smtp/email"
        payload = {"sender": {"email": remitente},
                   "to": [{"email": destino}],
                   "subject": _ASUNTO, "textContent": texto}
        headers = {"api-key": os.environ["BREVO_API_KEY"].strip(),
                   "content-type": "application/json",
                   "accept": "application/json"}
    elif metodo == "resend":
        url = "https://api.resend.com/emails"
        payload = {"from": remitente, "to": [destino],
                   "subject": _ASUNTO, "text": texto}
        headers = {"Authorization": f"Bearer {os.environ['RESEND_API_KEY'].strip()}",
                   "content-type": "application/json"}
    else:  # sendgrid
        url = "https://api.sendgrid.com/v3/mail/send"
        payload = {"personalizations": [{"to": [{"email": destino}]}],
                   "from": {"email": remitente}, "subject": _ASUNTO,
                   "content": [{"type": "text/plain", "value": texto}]}
        headers = {"Authorization": f"Bearer {os.environ['SENDGRID_API_KEY'].strip()}",
                   "content-type": "application/json"}
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            r.read()
        return True
    except urllib.error.HTTPError as e:
        # Surfacea el mensaje real del proveedor (p. ej. "Key not found").
        try:
            cuerpo = e.read().decode("utf-8", "replace")[:200]
        except Exception:  # noqa: BLE001
            cuerpo = ""
        raise RuntimeError(f"{metodo} HTTP {e.code}: {cuerpo or e.reason}")


def _enviar_email_webhook(destino: str, codigo: str) -> bool:
    """Envía por un relay HTTP propio (Google Apps Script, Cloudflare Worker,
    etc.). POST JSON {to, subject, text, secret} a EMAIL_WEBHOOK_URL."""
    import json
    import urllib.error
    import urllib.request
    url = os.environ["EMAIL_WEBHOOK_URL"].strip()
    payload = {"to": destino, "subject": _ASUNTO, "text": _cuerpo_email(codigo),
               "secret": os.environ.get("EMAIL_WEBHOOK_SECRET", "")}
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            cuerpo = r.read().decode("utf-8", "replace")[:200]
        # El relay debe responder OK/200; si devuelve un error textual, lo
        # propagamos para diagnóstico.
        if "error" in cuerpo.lower() and "ok" not in cuerpo.lower():
            raise RuntimeError(f"webhook respondió: {cuerpo}")
        return True
    except urllib.error.HTTPError as e:
        try:
            det = e.read().decode("utf-8", "replace")[:200]
        except Exception:  # noqa: BLE001
            det = ""
        raise RuntimeError(f"webhook HTTP {e.code}: {det or e.reason}")


def _enviar_email(destino: str, codigo: str) -> bool:
    metodo = metodo_email()
    if metodo is None:
        return False
    if metodo == "webhook":
        return _enviar_email_webhook(destino, codigo)
    if metodo in ("brevo", "resend", "sendgrid"):
        return _enviar_email_http(destino, codigo, metodo)
    # SMTP (respaldo; bloqueado en HF Spaces).
    import smtplib
    import ssl
    user = os.environ.get("EMAIL_USERNAME")
    host = os.environ.get("EMAIL_SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("EMAIL_SMTP_PORT", "465"))
    msg = EmailMessage()
    msg["Subject"] = _ASUNTO
    msg["From"] = _remitente()
    msg["To"] = destino
    msg.set_content(_cuerpo_email(codigo))
    with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(),
                          timeout=25) as s:
        s.login(user, os.environ.get("EMAIL_PASSWORD"))
        s.send_message(msg)
    return True


def validar_registro(email: str, nombre: str) -> tuple[bool, str, str]:
    """Verifica la unicidad correo↔nombre (relación 1:1).

    Reglas:
    - Un correo ya registrado no puede usarse con OTRO nombre.
    - Un nombre ya registrado no puede usarse con OTRO correo.

    Devuelve (ok, motivo, dato). motivo: 'ok' | 'email_tomado' |
    'nombre_tomado'. `dato` trae el nombre/correo en conflicto para el mensaje.
    """
    email = normalizar_email(email)
    nombre_n = (nombre or "").strip().lower()
    with _LOCK:
        # La unicidad solo aplica a CUENTAS REALES (con contraseña). Un correo
        # sin contraseña es un primer registro (o dato viejo) y no bloquea: su
        # nombre se fija al crear la contraseña. Un correo CON contraseña se
        # maneja en el login por contraseña, no acá.
        if nombre_n:
            for e, r in _DATA.items():
                if e == email or not r.get("password_hash"):
                    continue
                if (r.get("nombre") or "").strip().lower() == nombre_n:
                    return False, "nombre_tomado", e
    return True, "ok", ""


def registrar_binding(email: str, nombre: str) -> None:
    """Fija (persistiendo) la relación correo↔nombre desde el registro, aun
    antes de verificar, para reservar el par y que quede en la base."""
    email = normalizar_email(email)
    nombre = (nombre or "").strip()
    with _LOCK:
        r = _registro(email)
        if nombre and not (r.get("nombre") or "").strip():
            r["nombre"] = nombre
            r["actualizado"] = datetime.now().isoformat(timespec="seconds")
            _persistir()


def probar_smtp(destino: str) -> tuple[bool, str]:
    """Intenta enviar un correo de prueba y devuelve (ok, detalle) con el error
    real si falla. Uso de diagnóstico (admin)."""
    if not smtp_configurado():
        return False, ("SMTP no configurado: faltan EMAIL_USERNAME / "
                       "EMAIL_PASSWORD en las variables del Space.")
    try:
        _enviar_email(destino, "000000")
        return True, f"Correo de prueba enviado a {destino}."
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def solicitar_codigo(email: str, nombre: str = "") -> tuple[bool, str]:
    """Genera y envía un OTP al correo. Devuelve (ok, motivo).

    motivo: 'enviado' | 'email_invalido' | 'sin_smtp' | 'envio_fallo'.
    'sin_smtp' indica que no hay SMTP configurado (el caller puede optar por
    omitir la verificación en despliegues sin correo).
    """
    email = normalizar_email(email)
    if not email_valido(email):
        return False, "email_invalido"
    if not smtp_configurado():
        return False, "sin_smtp"
    codigo = f"{secrets.randbelow(900000) + 100000:06d}"
    _PENDIENTES[email] = {"hash": _hash_codigo(email, codigo),
                          "expira": time.time() + _OTP_TTL_SEG,
                          "nombre": (nombre or "").strip()}
    try:
        _enviar_email(email, codigo)
    except Exception as e:  # noqa: BLE001
        # Deja rastro en los logs del Space para diagnosticar (App Password,
        # 2FA, puerto, etc.) sin exponer el detalle al usuario final.
        import sys as _sys
        print(f"[SMTP] envío del código falló para {email}: "
              f"{type(e).__name__}: {e}", file=_sys.stderr, flush=True)
        return False, "envio_fallo"
    return True, "enviado"


def verificar_codigo(email: str, codigo: str) -> bool:
    email = normalizar_email(email)
    p = _PENDIENTES.get(email)
    if not p:
        return False
    if time.time() > p["expira"]:
        _PENDIENTES.pop(email, None)
        return False
    if not secrets.compare_digest(p["hash"], _hash_codigo(email, codigo.strip())):
        return False
    nombre = p.get("nombre", "")
    _PENDIENTES.pop(email, None)
    with _LOCK:
        r = _registro(email)
        r["verificado"] = True
        if nombre:
            r["nombre"] = nombre
        r["actualizado"] = datetime.now().isoformat(timespec="seconds")
        _persistir()
    return True


def marcar_verificado(email: str, nombre: str = "") -> None:
    """Marca un correo como verificado sin OTP (uso cuando no hay SMTP)."""
    email = normalizar_email(email)
    with _LOCK:
        r = _registro(email)
        r["verificado"] = True
        if nombre:
            r["nombre"] = nombre
        r["actualizado"] = datetime.now().isoformat(timespec="seconds")
        _persistir()


# ─────────────────── Contraseña (PBKDF2, stdlib) ───────────────────
def _hash_password(password: str, salt: str = None) -> str:
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                            bytes.fromhex(salt), 200_000).hex()
    return f"{salt}${h}"


def set_password(email: str, password: str, nombre: str = "") -> None:
    email = normalizar_email(email)
    with _LOCK:
        r = _registro(email)
        r["password_hash"] = _hash_password(password)
        if nombre:
            r["nombre"] = nombre
        r["actualizado"] = datetime.now().isoformat(timespec="seconds")
        _persistir()


def verificar_password(email: str, password: str) -> bool:
    email = normalizar_email(email)
    with _LOCK:
        r = _DATA.get(email)
        ph = r.get("password_hash") if r else None
    if not ph or "$" not in ph:
        return False
    salt, h = ph.split("$", 1)
    calc = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"),
                               bytes.fromhex(salt), 200_000).hex()
    return secrets.compare_digest(calc, h)


def tiene_password(email: str) -> bool:
    email = normalizar_email(email)
    with _LOCK:
        r = _DATA.get(email)
        return bool(r and r.get("password_hash"))


def quitar_password(email: str) -> None:
    """Quita la contraseña de un correo (uso admin): el usuario podrá volver a
    registrarse eligiendo una contraseña nueva."""
    email = normalizar_email(email)
    with _LOCK:
        r = _DATA.get(email)
        if r:
            r.pop("password_hash", None)
            r["actualizado"] = datetime.now().isoformat(timespec="seconds")
            _persistir()


# ─────────────────── Estado / cupo ───────────────────
def estado(email: str) -> dict:
    email = normalizar_email(email)
    with _LOCK:
        r = _registro(email)
        conteo = int(r.get("conteo", 0))
        licenciado = _licencia_activa(r)
        verificado = bool(r.get("verificado"))
        lh = r.get("licencia_hasta")
        con_password = bool(r.get("password_hash"))
    restantes = None if licenciado else max(0, LIMITE_GRATIS - conteo)
    return {"email": email, "nombre": r.get("nombre", ""),
            "verificado": verificado, "conteo": conteo,
            "limite": LIMITE_GRATIS, "restantes": restantes,
            "licenciado": licenciado, "licencia_hasta": lh,
            "tiene_password": con_password,
            "costo_bs": LICENCIA_COSTO_BS}


def puede_analizar(email: str) -> bool:
    st = estado(email)
    if not st["verificado"]:
        return False
    return st["licenciado"] or st["conteo"] < LIMITE_GRATIS


def motivo_bloqueo(email: str) -> str | None:
    st = estado(email)
    if not st["verificado"]:
        return "no_verificado"
    if not st["licenciado"] and st["conteo"] >= LIMITE_GRATIS:
        return "sin_cupo"
    return None


def consumir(email: str, nombre: str = "") -> tuple[bool, int | None]:
    """Reserva una ejecución. Devuelve (ok, restantes). restantes=None si el
    usuario tiene licencia activa (ilimitado). ok=False si no puede ejecutar."""
    email = normalizar_email(email)
    with _LOCK:
        r = _registro(email)
        if not r.get("verificado"):
            return False, 0
        licenciado = _licencia_activa(r)
        if not licenciado and int(r.get("conteo", 0)) >= LIMITE_GRATIS:
            return False, 0
        r["conteo"] = int(r.get("conteo", 0)) + 1
        if nombre:
            r["nombre"] = nombre
        r["actualizado"] = datetime.now().isoformat(timespec="seconds")
        _persistir()
        restantes = None if licenciado else max(0, LIMITE_GRATIS - r["conteo"])
        return True, restantes


# Carga inicial (local + HF).
_inicializar()
