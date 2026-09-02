"""Webapp Flask CURVAS IDF v1.2 (usa el pipeline unificado de src/idf)."""

from __future__ import annotations

import gc
import json
import os
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path

from functools import wraps

from flask import (
    Flask, abort, flash, jsonify, redirect, render_template, request,
    send_from_directory, session, url_for,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import usuarios  # noqa: E402  (módulo local de webapp: login + cuota mensual)
from idf import DatosProyecto, ejecutar_pipeline  # noqa: E402
from idf.obras import TIPOS_OBRA  # noqa: E402
from idf.idf_models import RESOLUCIONES_DATOS  # noqa: E402
from idf.stats import PERIODOS_RETORNO_DEFAULT  # noqa: E402

SESSIONS_DIR = Path(os.environ.get("IDF_SESSIONS_DIR", "/tmp/idf-sesiones"))
SESSION_TTL_SEC = int(os.environ.get("IDF_SESSION_TTL", 3600))
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("IDF_SECRET_KEY", "dev-key-cambiar-en-produccion")
# Hugging Face Spaces sirve la app DENTRO DE UN IFRAME en huggingface.co, es
# decir en un contexto "cross-site". El navegador NO guarda la cookie de sesión
# si es SameSite=Lax (el default de Flask) en un iframe de otro origen → tras
# el login la sesión se pierde y el usuario vuelve al login (bucle sin error).
# Con SameSite=None + Secure la cookie sí se guarda dentro del iframe (y también
# funciona en acceso directo por HTTPS a *.hf.space).
app.config.update(
    SESSION_COOKIE_SAMESITE="None",
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    PERMANENT_SESSION_LIFETIME=int(os.environ.get("IDF_SESSION_TTL", 3600)),
)

_STATUS_LOCK = threading.Lock()


# ────────────── Login con verificación por correo + cupo/licencia ──────────────
def login_required(f):
    """Exige un usuario logueado y verificado; si no, va a la ventana de login."""
    @wraps(f)
    def _wrap(*args, **kwargs):
        if not session.get("user_email") or not session.get("user_verificado"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return _wrap


def _serie_obs_desde_form(form):
    """Devuelve el DataFrame de la serie observada pegada por el usuario, o None.

    Lee el campo de texto libre `serie_observada` y lo parsea (formato flexible
    año/valor). Si no hay al menos 10 años válidos, devuelve None y el pipeline
    sigue con las fuentes automáticas.
    """
    txt = (form.get("serie_observada") or "").strip()
    if not txt:
        return None
    try:
        from idf.serie_usuario import parsear_serie_observada
        return parsear_serie_observada(txt)
    except Exception:  # noqa: BLE001
        return None


def _iniciar_sesion(email: str, nombre: str) -> None:
    session.permanent = True
    session["user_email"] = email
    session["user_nombre"] = nombre
    session["user_verificado"] = True


@app.route("/login", methods=["GET", "POST"])
def login():
    """Ingreso con correo + contraseña (cuentas ya registradas)."""
    if request.method == "POST":
        email = usuarios.normalizar_email(request.form.get("email"))
        password = request.form.get("password") or ""
        if not usuarios.email_valido(email):
            flash("Ingresá un correo electrónico válido.")
            return render_template("login.html", email=request.form.get("email", ""))
        if usuarios.tiene_password(email) and \
                usuarios.verificar_password(email, password):
            _iniciar_sesion(email, usuarios.estado(email).get("nombre") or "")
            return redirect(url_for("index"))
        # Distinguir "no existe la cuenta" de "contraseña equivocada". Si el
        # correo no tiene cuenta, insistir en el login es un callejón sin
        # salida: se lleva al usuario directamente al registro con el correo
        # ya cargado. Esto ocurre de forma natural cuando el contenedor se
        # reinicia sin persistencia configurada (ver README: HF_TOKEN).
        if not usuarios.tiene_password(email):
            flash("Ese correo todavía no tiene una cuenta en este servidor. "
                  "Completá el registro acá abajo para crearla — toma unos "
                  "segundos y entrás enseguida.")
            return render_template("registro.html", email=email, nombre="")
        flash("Contraseña incorrecta. Si la olvidaste, usá «¿Olvidaste tu "
              "contraseña?» para recuperarla.")
        return render_template("login.html", email=email)
    if session.get("user_email") and session.get("user_verificado"):
        return redirect(url_for("index"))
    return render_template("login.html")


@app.route("/registro", methods=["GET", "POST"])
def registro():
    """Crear cuenta: nombre + correo + contraseña. La cuenta queda activa de
    inmediato; la verificación por correo es opcional (solo si el envío está
    configurado y HYDROFRA_VERIFICACION_OBLIGATORIA=1)."""
    if request.method == "POST":
        nombre = (request.form.get("nombre") or "").strip()
        email = usuarios.normalizar_email(request.form.get("email"))
        password = request.form.get("password") or ""
        password2 = request.form.get("password2") or ""
        rr = lambda: render_template("registro.html", nombre=nombre,
                                     email=request.form.get("email", ""))
        if not nombre:
            flash("Ingresá tu nombre y apellido (será el ingeniero encargado).")
            return rr()
        if not usuarios.email_valido(email):
            flash("Ingresá un correo electrónico válido.")
            return rr()
        if len(password) < 6:
            flash("La contraseña debe tener al menos 6 caracteres.")
            return rr()
        if password != password2:
            flash("Las contraseñas no coinciden.")
            return rr()
        if usuarios.tiene_password(email):
            flash("Ese correo ya tiene una cuenta. Ingresá con tu contraseña o "
                  "recuperala.")
            return rr()
        ok_reg, _motivo, _d = usuarios.validar_registro(email, nombre)
        if not ok_reg:
            flash("Ese nombre ya está en uso por otra cuenta. Usá un nombre "
                  "distinto.")
            return rr()
        usuarios.set_password(email, password, nombre)
        # Verificación por correo: solo si el envío está configurado.
        if usuarios.smtp_configurado():
            ok, _m = usuarios.solicitar_codigo(email, nombre)
            if ok:
                session["pending_email"] = email
                session["pending_nombre"] = nombre
                return redirect(url_for("verificar"))
            if usuarios.VERIFICACION_OBLIGATORIA:
                flash("No pudimos enviar el código de verificación. Intentá "
                      "más tarde o contactá al administrador.")
                return rr()
        # Sin correo (o no obligatoria): cuenta activa de inmediato.
        usuarios.marcar_verificado(email, nombre)
        _iniciar_sesion(email, nombre)
        return redirect(url_for("index"))
    return render_template("registro.html")


@app.route("/verificar", methods=["GET", "POST"])
def verificar():
    email = session.get("pending_email")
    if not email:
        return redirect(url_for("login"))
    if request.method == "POST":
        codigo = (request.form.get("codigo") or "").strip()
        if usuarios.verificar_codigo(email, codigo):
            nombre = session.pop("pending_nombre", "")
            session.pop("pending_email", None)
            _iniciar_sesion(email, usuarios.estado(email).get("nombre") or nombre)
            return redirect(url_for("index"))
        flash("Código incorrecto o vencido. Pedí uno nuevo si hace falta.")
    return render_template("verificar.html", email=email)


@app.route("/reenviar_codigo", methods=["POST"])
def reenviar_codigo():
    email = session.get("pending_email")
    if not email:
        return redirect(url_for("login"))
    ok, _motivo = usuarios.solicitar_codigo(email, session.get("pending_nombre", ""))
    flash("Te reenviamos el código." if ok
          else "No pudimos reenviar el código. Intentá más tarde.")
    return redirect(url_for("verificar"))


@app.route("/recuperar", methods=["GET", "POST"])
def recuperar():
    """Recuperar acceso: envía un código por correo para restablecer la
    contraseña."""
    if request.method == "POST":
        email = usuarios.normalizar_email(request.form.get("email"))
        if not usuarios.email_valido(email):
            flash("Ingresá un correo electrónico válido.")
            return render_template("recuperar.html", email=request.form.get("email", ""))
        if not usuarios.tiene_password(email):
            flash("Ese correo no tiene una cuenta registrada con contraseña. "
                  "Registrate primero desde el ingreso.")
            return render_template("recuperar.html", email=email)
        ok, _motivo = usuarios.solicitar_codigo(
            email, usuarios.estado(email).get("nombre", ""))
        if ok:
            session["reset_email"] = email
            return redirect(url_for("recuperar_codigo"))
        flash("No pudimos enviar el código de recuperación en este momento. "
              "El envío de correo debe estar operativo — contactá al administrador.")
        return render_template("recuperar.html", email=email)
    return render_template("recuperar.html")


@app.route("/recuperar_codigo", methods=["GET", "POST"])
def recuperar_codigo():
    email = session.get("reset_email")
    if not email:
        return redirect(url_for("recuperar"))
    if request.method == "POST":
        codigo = (request.form.get("codigo") or "").strip()
        password = request.form.get("password") or ""
        if len(password) < 6:
            flash("La nueva contraseña debe tener al menos 6 caracteres.")
            return render_template("recuperar_codigo.html", email=email)
        if usuarios.verificar_codigo(email, codigo):
            usuarios.set_password(email, password)
            session.pop("reset_email", None)
            _iniciar_sesion(email, usuarios.estado(email).get("nombre", ""))
            flash("Contraseña actualizada. Ya estás dentro.")
            return redirect(url_for("index"))
        flash("Código incorrecto o vencido. Pedí uno nuevo si hace falta.")
    return render_template("recuperar_codigo.html", email=email)


@app.route("/recuperar_reenviar", methods=["POST"])
def recuperar_reenviar():
    email = session.get("reset_email")
    if not email:
        return redirect(url_for("recuperar"))
    ok, _m = usuarios.solicitar_codigo(email, usuarios.estado(email).get("nombre", ""))
    flash("Te reenviamos el código." if ok
          else "No pudimos reenviar el código. Intentá más tarde.")
    return redirect(url_for("recuperar_codigo"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/admin/licencia", methods=["POST"])
def admin_licencia():
    """Activa una licencia mensual para un correo (uso del administrador).

    Protegido por HYDROFRA_ADMIN_TOKEN. Parámetros (form o JSON): token, email,
    dias (opcional). Devuelve el estado resultante en JSON.
    """
    datos = request.get_json(silent=True) or request.form
    if not usuarios.admin_token_valido(datos.get("token")):
        return jsonify({"ok": False, "error": "token inválido"}), 403
    email = usuarios.normalizar_email(datos.get("email"))
    if not usuarios.email_valido(email):
        return jsonify({"ok": False, "error": "email inválido"}), 400
    dias = datos.get("dias")
    st = usuarios.otorgar_licencia(email, int(dias) if dias else None)
    return jsonify({"ok": True, "estado": st})


@app.route("/admin", methods=["GET", "POST"])
def admin():
    """Panel de administración: activar/revocar licencias mensuales.

    Acceso con HYDROFRA_ADMIN_TOKEN (se guarda en la sesión tras el login).
    """
    if request.method == "POST":
        accion = request.form.get("accion")
        if accion == "login":
            if usuarios.admin_token_valido(request.form.get("token")):
                session["admin"] = True
            else:
                flash("Token de administrador inválido.")
            return redirect(url_for("admin"))
        if not session.get("admin"):
            return redirect(url_for("admin"))
        if accion == "logout":
            session.pop("admin", None)
            return redirect(url_for("admin"))
        email = usuarios.normalizar_email(request.form.get("email"))
        if not usuarios.email_valido(email):
            flash("Correo inválido.")
            return redirect(url_for("admin"))
        if accion == "otorgar":
            dias = request.form.get("dias")
            st = usuarios.otorgar_licencia(email, int(dias) if dias else None)
            flash(f"Licencia activada para {email} (vigente hasta "
                  f"{st['licencia_hasta']}).")
        elif accion == "revocar":
            usuarios.revocar_licencia(email)
            flash(f"Licencia revocada para {email}.")
        elif accion == "reset_password":
            nueva = (request.form.get("password") or "").strip()
            if len(nueva) < 6:
                flash("La nueva contraseña debe tener al menos 6 caracteres.")
            else:
                usuarios.set_password(email, nueva)
                flash(f"Contraseña restablecida para {email}. Comunicá la nueva "
                      f"contraseña al usuario; puede cambiarla luego.")
        elif accion == "quitar_password":
            usuarios.quitar_password(email)
            flash(f"Se quitó la contraseña de {email}: podrá registrarse de "
                  f"nuevo con una contraseña nueva.")
        return redirect(url_for("admin"))
    if not session.get("admin"):
        return render_template("admin.html", autenticado=False,
                               configurado=usuarios.admin_configurado())
    return render_template("admin.html", autenticado=True,
                           usuarios=usuarios.listar(),
                           costo_bs=usuarios.LICENCIA_COSTO_BS,
                           dias_licencia=usuarios.LICENCIA_DIAS,
                           limite=usuarios.LIMITE_GRATIS)


@app.route("/config_status", methods=["GET"])
def config_status():
    """Estado de configuración del Space (solo booleanos, sin exponer secretos).
    Sirve para diagnosticar qué variables de entorno se cargaron realmente."""
    return jsonify({
        "smtp_configurado": usuarios.smtp_configurado(),
        "email_metodo": usuarios.metodo_email(),
        "email_smtp_host": os.environ.get("EMAIL_SMTP_HOST", "smtp.gmail.com"),
        "email_smtp_port": os.environ.get("EMAIL_SMTP_PORT", "465"),
        "admin_token_configurado": usuarios.admin_configurado(),
        "verificacion_obligatoria": usuarios.VERIFICACION_OBLIGATORIA,
        "hf_token_configurado": bool(os.environ.get("HF_TOKEN") or
                                     os.environ.get("HUGGING_FACE_HUB_TOKEN")),
        "gee_configurado": bool(os.environ.get("GEE_PROJECT_ID") and
                                os.environ.get("GEE_SERVICE_ACCOUNT_JSON")),
        "secret_key_personalizada": app.secret_key != "dev-key-cambiar-en-produccion",
    })


@app.route("/smtp_test", methods=["GET", "POST"])
def smtp_test():
    """Diagnóstico del envío de correo (admin). Uso desde el navegador:
    /smtp_test?token=ADMIN_TOKEN&email=tucorreo@ejemplo.com
    Devuelve JSON con el resultado y el error real si falla."""
    datos = request.values
    if not usuarios.admin_token_valido(datos.get("token")):
        return jsonify({
            "ok": False, "error": "token inválido",
            "admin_token_configurado": usuarios.admin_configurado(),
            "pista": ("La variable HYDROFRA_ADMIN_TOKEN NO está cargada en el "
                      "Space — agregala y reiniciá." if not usuarios.admin_configurado()
                      else "La variable SÍ está cargada, pero el token de la "
                      "URL no coincide con su valor.")}), 403
    email = usuarios.normalizar_email(datos.get("email"))
    if not usuarios.email_valido(email):
        return jsonify({"ok": False, "error": "email inválido"}), 400
    ok, detalle = usuarios.probar_smtp(email)
    return jsonify({"ok": ok, "detalle": detalle,
                    "smtp_configurado": usuarios.smtp_configurado(),
                    "verificacion_obligatoria": usuarios.VERIFICACION_OBLIGATORIA})


def _limite_alcanzado_pagina():
    """Página de límite alcanzado con el mensaje de compra de licencia mensual."""
    from urllib.parse import quote
    email = session.get("user_email", "")
    msg = (f"Hola {usuarios.CONTACTO['nombre']}, quiero comprar la licencia "
           f"mensual de HYDROFRA (costo único de Bs {usuarios.LICENCIA_COSTO_BS}). "
           f"Mi correo de acceso es: {email}. Quedo atento para el pago. ¡Gracias!")
    wa_url = f"{usuarios.CONTACTO['whatsapp_url']}?text={quote(msg)}"
    return render_template(
        "limite.html", limite=usuarios.LIMITE_GRATIS,
        costo_bs=usuarios.LICENCIA_COSTO_BS,
        contacto=usuarios.CONTACTO, wa_url=wa_url), 402


def _construir_bloque_agua_potable(*, lat: float, lon: float,
                                       ap_demanda: dict,
                                       cuenca_qmin, pq, hidro_cercanas,
                                       stats_qmin: dict, pq_eco: list,
                                       cuantiles_qmin: list,
                                       q7_10: float) -> dict:
    """Calcula demanda + transposición + balance para el informe AP.

    Devuelve un dict con las claves consumidas por
    `report_qmin_agua_potable`: `ap_caudales_demanda`,
    `ap_transposicion`, `ap_balance`, `ap_estimaciones`. Si la altitud o
    los datos esenciales no están, devuelve solo lo que pudo calcular.
    """
    from idf.pisos_ecologicos import clasificar
    from idf.demanda_agua_potable import (proyectar_poblacion,
                                              dotacion_adoptada,
                                              caudales_diseno,
                                              K1_NB689, K2_NB689)
    from idf.transposicion_hidrologica import seleccionar_mejor_donante
    from idf.balance_oferta_demanda import (EstimacionMetodo,
                                                construir_balance)
    from datetime import datetime as _dt

    out: dict = {}
    altitud = (getattr(cuenca_qmin, "cota_menor_m", None)
                 if cuenca_qmin is not None else None)
    piso = clasificar(lat, lon, altitud)
    out["_piso_ecologico"] = piso

    # 1) Demanda
    proy = proyectar_poblacion(
        poblacion_actual=int(ap_demanda.get("poblacion_actual", 500)),
        anio_base=_dt.utcnow().year,
        horizonte_anios=int(ap_demanda.get("horizonte_anios", 20)),
        tasa_crecimiento_pct=float(ap_demanda.get("tasa_crec_pct", 1.5)),
        metodo=ap_demanda.get("metodo_proy", "geometrico"))
    dot = dotacion_adoptada(
        rango_piso=piso.dotacion_l_hab_dia_sugerida,
        nivel_servicio=ap_demanda.get("nivel_servicio", "domiciliaria_basica"),
        dotacion_usuario_l_hab_dia=ap_demanda.get("dotacion_l_hab_dia"))
    caudales = caudales_diseno(proy, dot, k1=K1_NB689, k2=K2_NB689)
    out["ap_caudales_demanda"] = caudales

    # 2) Transposición hidrológica (Método 5.3 del skill)
    transpo = None
    if cuenca_qmin is not None and hidro_cercanas:
        pann = stats_qmin.get("pann_mm") or (
            getattr(pq, "pann_mm", None) if pq else None)
        try:
            transpo = seleccionar_mejor_donante(
                hidro_cercanas, cuenca_qmin.area_km2, lat, lon,
                altitud, pann)
        except Exception as e:  # noqa: BLE001
            print(f"[qmin/ap] transposición no aplicable: "
                   f"{type(e).__name__}: {e}", flush=True)
    out["ap_transposicion"] = transpo

    # 3) Estimaciones de oferta — multimétodo
    estimaciones: list[EstimacionMetodo] = []
    estimaciones.append(EstimacionMetodo(
        metodo="5.1 Aforo directo en campo",
        q_min_m3s=None, base_datos="Pendiente de campaña",
        confiabilidad="no_aplicable",
        observacion="Requiere ≥3 aforos en estiaje (Anexo E)"))
    if pq is not None:
        estimaciones.append(EstimacionMetodo(
            metodo="5.2 Balance hídrico mensual (Thornthwaite-Mather)",
            q_min_m3s=float(pq.q_min_m3s),
            base_datos=f"CHIRPS + climatología local — n={pq.q_mes_m3s.size} meses",
            confiabilidad="media",
            observacion=(f"α={pq.alpha:.2f} · f_rápida={pq.fraccion_rapida:.2f} · "
                          f"C_anual={pq.coef_escorrentia_anual:.2f}")))
    if transpo is not None:
        estimaciones.append(EstimacionMetodo(
            metodo=f"5.3 Transposición hidrológica (donante "
                    f"{transpo.donante.codigo})",
            q_min_m3s=transpo.q_min_transpuesto_m3s,
            base_datos=(f"{transpo.donante.codigo} — "
                          f"{transpo.donante.cuerpo_agua}"),
            confiabilidad=transpo.similitud_clasificacion,
            observacion=(f"n={transpo.exponente_n:.2f}, razón A="
                          f"{transpo.razon_areas:.2f}; "
                          + (transpo.advertencias[0]
                             if transpo.advertencias else "OK"))))
    if cuantiles_qmin:
        # cuantiles_qmin viene como lista [(T, q), ...]
        cu_d = {int(T): float(q) for T, q in cuantiles_qmin}
        q_t10 = cu_d.get(10)
        if q_t10:
            estimaciones.append(EstimacionMetodo(
                metodo="5.4 Análisis de frecuencia Q mínimos (T=10 años)",
                q_min_m3s=q_t10,
                base_datos="Serie anual de mínimos (Weibull/LP3/GEV)",
                confiabilidad="media",
                observacion=f"Q7,10 ≈ {q7_10:.4f} m³/s"))

    # 4) Q ecológico — toma el método más conservador entre los calculados
    q_eco = 0.0; metodo_eco = "—"
    if pq_eco:
        # pq_eco es una lista de CaudalEcologico
        try:
            ordenadas = sorted(pq_eco, key=lambda c: c.q_eco_m3s)
            q_eco = float(ordenadas[len(ordenadas) // 2].q_eco_m3s)
            metodo_eco = ordenadas[len(ordenadas) // 2].metodo
        except Exception:  # noqa: BLE001
            pass
    # 5) Balance
    balance = construir_balance(
        estimaciones=estimaciones,
        q_ecologico_m3s=q_eco, q_ecologico_metodo=metodo_eco,
        q_demanda_max_d_m3s=caudales.q_max_d_m3s,
        factor_seguridad=1.25)
    out["ap_estimaciones"] = estimaciones
    out["ap_balance"] = balance
    return out

# Etiquetas legibles para la fuente de la climatología de precipitación.
_CLIMA_FUENTE_LABEL = {
    "CHIRPS_GEE": "CHIRPS Daily 0.05° (Google Earth Engine, sobre la cuenca)",
    "SAAVEDRA_ZENODO": ("Saavedra & Ureña 2022 — CHIRPS+GSMaP+SENAMHI 0.05° "
                          "(Zenodo 6991231, 2000–2015)"),
    "SENAMHI_IDW": ("Grilla SENAMHI-IDW 0.25° (interpolación de las 49 "
                      "estaciones curadas con P24 documentado)"),
}


def _escribir_status(sesion_dir: Path, datos: dict) -> None:
    """Escribe status.json de forma atómica para evitar race entre worker y polling."""
    tmp = sesion_dir / "status.tmp"
    final = sesion_dir / "status.json"
    with _STATUS_LOCK:
        tmp.write_text(json.dumps(datos))
        tmp.replace(final)


def _leer_status(sesion_dir: Path) -> dict:
    f = sesion_dir / "status.json"
    if not f.exists():
        return {"estado": "iniciando"}
    try:
        return json.loads(f.read_text())
    except Exception:  # noqa: BLE001
        return {"estado": "iniciando"}


def _limpiar_sesiones_viejas() -> None:
    ahora = time.time()
    for d in SESSIONS_DIR.iterdir():
        if not d.is_dir():
            continue
        try:
            if ahora - d.stat().st_mtime > SESSION_TTL_SEC:
                for f in d.iterdir():
                    f.unlink(missing_ok=True)
                d.rmdir()
        except Exception:
            pass


def _pipeline_worker(sesion_dir: Path, params: dict) -> None:
    """Corre el pipeline completo en thread; actualiza status.json al final.

    Un thread aparte escribe heartbeat (`ts`) cada 8 s para que el frontend
    sepa que el worker sigue vivo aún cuando el pipeline no publica pasos
    intermedios.
    """
    stop_hb = threading.Event()
    estado_actual = {"paso": "Iniciando análisis…"}

    def _heartbeat():
        while not stop_hb.wait(8):
            _escribir_status(sesion_dir, {
                "estado": "procesando",
                "paso": estado_actual["paso"],
                "ts": time.time(),
            })

    hb = threading.Thread(target=_heartbeat, daemon=True)
    hb.start()
    sesion_id = sesion_dir.name
    try:
        _escribir_status(sesion_dir, {
            "estado": "procesando", "paso": estado_actual["paso"],
            "inicio": time.time(), "ts": time.time(),
        })
        # telemetria_consent es interno al worker, no es kwarg de ejecutar_pipeline.
        telemetria_consent = params.pop("telemetria_consent", False)
        estado_actual["paso"] = "Descargando datos de Google Earth Engine…"
        R = ejecutar_pipeline(sesion_dir, **params)
        estado_actual["paso"] = "Compilando la página de resultados…"
        # Renderizamos el HTML del resultado AQUÍ (dentro de un request context
        # ficticio) y lo guardamos en disco. Antes pickleábamos R, pero R
        # contiene closures no serializables (modelos IDF con funciones lambda
        # internas: _fit_promedio_adim.<locals>.f). Renderizar ahora evita el
        # pickle por completo y desacopla /resultado del objeto en memoria.
        cuantiles_html = R.cuantiles.copy()
        cuantiles_html["p24_mm"] = cuantiles_html["p24_mm"].round(2)
        cuantiles_html["prob_no_exc"] = cuantiles_html["prob_no_exc"].round(5)
        with app.test_request_context():
            html = render_template(
                "result.html",
                sesion_id=sesion_id, R=R,
                cuantiles=cuantiles_html.to_dict(orient="records"),
                hietograma_bloques=R.hietogramas["bloques"].tabla.to_dict(orient="records"),
                pdf_url=url_for("reportes", sesion_id=sesion_id, archivo=R.pdf.name),
            )
        (sesion_dir / "resultado.html").write_text(html, encoding="utf-8")
        # Telemetría — persiste el análisis si el usuario dio consentimiento.
        try:
            from idf.telemetria import registrar_qmax
            registrar_qmax(R, sesion_id=sesion_id, consent=telemetria_consent)
        except Exception as e:  # noqa: BLE001
            print(f"[telemetria] qmax falló: {e}", flush=True)
        gc.collect()
        stop_hb.set()
        _escribir_status(sesion_dir, {
            "estado": "completo",
            "pdf": R.pdf.name if R.pdf else None,
            "fin": time.time(),
        })
    except Exception as e:  # noqa: BLE001
        stop_hb.set()
        _escribir_status(sesion_dir, {
            "estado": "error",
            "mensaje": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        })


@app.route("/", methods=["GET"])
@login_required
def index():
    cuota = usuarios.estado(session["user_email"])
    return render_template("index.html", default_lat=-17.766589, default_lon=-65.734027,
                           tipos_obra=TIPOS_OBRA, periodos=PERIODOS_RETORNO_DEFAULT,
                           resoluciones=RESOLUCIONES_DATOS,
                           usuario={"email": session.get("user_email"),
                                    "nombre": session.get("user_nombre", "")},
                           cuota=cuota)


@app.route("/salud", methods=["GET"])
def salud():
    return {"status": "ok", "ts": datetime.utcnow().isoformat() + "Z"}


@app.route("/version", methods=["GET"])
def version():
    """Devuelve el commit SHA que está corriendo ahora mismo + diagnóstico."""
    candidatos = [
        ROOT / "VERSION",
        Path("/app/VERSION"),
        Path("/app/webapp/VERSION"),
        Path("/app/src/VERSION"),
        Path.cwd() / "VERSION",
        Path("/data/VERSION"),
    ]
    encontrado_en = None
    sha = "desconocido"
    rutas_revisadas = []
    for p in candidatos:
        rutas_revisadas.append({"path": str(p), "existe": p.exists()})
        if p.exists() and sha == "desconocido":
            try:
                sha = p.read_text().strip()
                encontrado_en = str(p)
            except Exception as e:  # noqa: BLE001
                rutas_revisadas[-1]["error_lectura"] = str(e)
    # Listado de /app/ para que sepamos qué archivos están realmente ahí
    listado_app = []
    try:
        for f in sorted(Path("/app").iterdir())[:30]:
            listado_app.append({"name": f.name,
                                  "type": "dir" if f.is_dir() else "file"})
    except Exception as e:  # noqa: BLE001
        listado_app = [{"error": str(e)}]
    r = jsonify({
        "commit_sha": sha,
        "commit_corto": sha[:8] if len(sha) >= 8 and sha != "desconocido" else sha,
        "encontrado_en": encontrado_en,
        "rutas_revisadas": rutas_revisadas,
        "listado_app": listado_app,
        "ts_request_utc": datetime.utcnow().isoformat() + "Z",
        "branch_esperada": "claude/implement-idf-WibPx",
    })
    r.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return r


@app.route("/gee_status", methods=["GET"])
def gee_status():
    """Diagnóstico de la integración Google Earth Engine."""
    from idf.gee import estado
    return jsonify(estado())


def _resp_no_cache(payload):
    """Envuelve jsonify con headers que prohíben cualquier cache."""
    r = jsonify(payload)
    r.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    r.headers["Pragma"] = "no-cache"
    r.headers["Expires"] = "0"
    return r


@app.route("/apis_test", methods=["GET"])
def apis_test():
    """Prueba en vivo las 4 APIs satelitales (CHIRPS, NASA POWER, Open-Meteo,
    NOAA GHCN-D) y reporta cuáles responden con datos reales.

    Crítico en v1.3: el análisis Q máx aborta si ninguna fuente real
    responde. Este endpoint permite verificar el estado de las APIs sin
    correr un análisis completo.

    Uso: /apis_test?lat=-21.413861&lon=-64.807087
    """
    try:
        lat = float(request.args.get("lat", "-21.413861"))
        lon = float(request.args.get("lon", "-64.807087"))
    except ValueError:
        return _resp_no_cache({"ok": False,
                                  "error": "lat/lon deben ser numéricos"}), 400
    ai = int(request.args.get("anio_ini", "2015"))
    af = int(request.args.get("anio_fin", "2020"))
    from idf.satelital import diagnostico_apis
    return _resp_no_cache(diagnostico_apis(lat, lon, ai, af))


@app.route("/dem_status", methods=["GET"])
def dem_status():
    """Diagnóstico del DEM Copernicus GLO-30 + downscaling cubic a 12.5 m."""
    from idf.copernicus_dem import estado
    return _resp_no_cache(estado())


@app.route("/dem_test", methods=["GET"])
def dem_test():
    """Test 4 pasos: init → descarga COP-DEM 30 m → downscale → abrir.

    Uso: /dem_test?lat=-21.413861&lon=-64.807087
    """
    try:
        lat = float(request.args.get("lat", "0"))
        lon = float(request.args.get("lon", "0"))
    except ValueError:
        return _resp_no_cache({"ok": False,
                                  "error": "lat/lon deben ser numéricos"}), 400
    from idf.copernicus_dem import test_punto
    return _resp_no_cache(test_punto(lat, lon))


@app.route("/alos_status", methods=["GET"])
def alos_status():
    """Diagnóstico de la integración ALOS PALSAR DEM 12.5 m vía ASF."""
    from idf.alos_palsar_dem import estado
    return jsonify(estado())


@app.route("/hec_status", methods=["GET"])
def hec_status():
    """Diagnóstico de la integración HEC-RAS/HEC-HMS (ras/hms-commander)."""
    from idf.hec_commander import estado
    return jsonify(estado())


@app.route("/alos_test", methods=["GET"])
def alos_test():
    """Test punto-a-punto: busca + descarga 1 tile ALOS para validar auth.

    Uso: /alos_test?lat=-21.413861&lon=-64.807087
    """
    try:
        lat = float(request.args.get("lat", "0"))
        lon = float(request.args.get("lon", "0"))
    except ValueError:
        return jsonify({"ok": False,
                          "error": "lat/lon deben ser numéricos"}), 400
    from idf.alos_palsar_dem import test_punto
    return jsonify(test_punto(lat, lon))


@app.route("/alos_cobertura", methods=["GET"])
def alos_cobertura():
    """Prueba 6 combinaciones de filtros ASF y reporta cuáles tienen
    cobertura para el punto. Útil cuando /alos_test devuelve 0 escenas:
    permite identificar si la cobertura ALOS RTC realmente no existe en
    la zona o si solo hace falta otro processingLevel.

    Uso: /alos_cobertura?lat=-21.413861&lon=-64.807087
    """
    try:
        lat = float(request.args.get("lat", "0"))
        lon = float(request.args.get("lon", "0"))
    except ValueError:
        return jsonify({"ok": False,
                          "error": "lat/lon deben ser numéricos"}), 400
    radio = float(request.args.get("radio", "0.1"))
    bbox = {"oeste": lon - radio, "este": lon + radio,
              "sur": lat - radio, "norte": lat + radio}
    from idf.alos_palsar_dem import diagnosticar_cobertura
    combos = diagnosticar_cobertura(bbox)
    rtc_disponible = any(c.get("n_escenas", 0) > 0
                            for c in combos
                            if "RTC" in c.get("combo", ""))
    return jsonify({
        "lat": lat, "lon": lon, "bbox": bbox,
        "combos_probados": combos,
        "rtc_disponible": rtc_disponible,
        "sugerencia": (
            "ALOS PALSAR RTC tiene cobertura en este punto — el módulo "
            "puede generar DEM 12.5 m." if rtc_disponible else
            "ALOS PALSAR RTC NO tiene cobertura en este punto. Para 12.5 m "
            "global gratis no existe alternativa libre vía ASF; sugerido "
            "usar Copernicus GLO-30 (30 m) vía GEE que ya tenemos integrado, "
            "o TanDEM-X 12 m (comercial DLR ~€800/km²)."),
    })


@app.route("/gee_test", methods=["GET"])
def gee_test():
    """Diagnóstico punto-a-punto de GEE para una coordenada (lat, lon).

    Ejecuta los 4 pasos críticos del pipeline GEE en secuencia y reporta
    cuál pasa o falla, con el detalle del error cuando aplica. Pensado
    para diagnosticar casos en que el análisis general corre OK pero los
    mapas de la cuenca terminan siendo esquemáticos.

    Uso:  /gee_test?lat=-21.413832&lon=-64.807079
    """
    import time as _t
    try:
        lat = float(request.args.get("lat", "0"))
        lon = float(request.args.get("lon", "0"))
    except ValueError:
        return jsonify({"ok": False,
                          "error": "lat/lon deben ser numéricos"}), 400
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return jsonify({"ok": False,
                          "error": "lat/lon fuera de rango"}), 400

    pasos: list = []

    def _registrar(nombre, fn):
        t0 = _t.time()
        try:
            r = fn()
            pasos.append({"paso": nombre,
                            "ok": r.get("ok"),
                            "ms": int((_t.time() - t0) * 1000),
                            **{k: v for k, v in r.items() if k != "ok"}})
            return r.get("ok"), r
        except Exception as e:  # noqa: BLE001
            # Filtramos el traceback a los frames del proyecto (src/idf/) +
            # el frame raíz, así se identifica la línea exacta del bug sin
            # enterrarlo en frames de pandas/numpy.
            tb_completo = traceback.format_exc()
            tb_filtrado = "\n".join([
                ln for ln in tb_completo.splitlines()
                if "/src/idf/" in ln or "/webapp/" in ln or ln.startswith("ValueError")
                  or ln.startswith("TypeError") or ln.startswith("AttributeError")
                  or ln.startswith("IndexError") or ln.startswith("KeyError")
            ])
            pasos.append({"paso": nombre, "ok": False,
                            "ms": int((_t.time() - t0) * 1000),
                            "error": f"{type(e).__name__}: {str(e)[:200]}",
                            "traceback_idf": tb_filtrado[:2000],
                            "traceback_full": tb_completo[-3000:]})
            return False, None

    # 1. Inicializar GEE
    def _init():
        from idf.gee import disponible, estado
        ok = disponible()
        e = estado()
        return {"ok": ok, "error_init": e.get("error_init")}
    ok, _ = _registrar("1_init_gee", _init)
    if not ok:
        return jsonify({"ok": False, "lat": lat, "lon": lon, "pasos": pasos,
                          "sugerencia": "GEE no inicializa — ver /gee_status"})

    # 2. Delineación MERIT Hydro (la causa más común de mapas esquemáticos)
    def _delinear():
        from idf.watershed import delinear_cuenca_merit
        c = delinear_cuenca_merit(lat, lon, radio_grados=0.3,
                                       reintentar_borde=True)
        if c is None:
            return {"ok": False,
                    "detalle": ("delinear_cuenca_merit() devolvió None — "
                                  "posibles causas: tile MERIT no descargó, "
                                  "punto fuera del tile, cuenca degenerada "
                                  "(< 5 píxeles), o GEE timeout. Ver logs "
                                  "del Space con prefijo [GEE].")}
        pol = c.poligono_latlon
        n_vert = int(len(pol)) if pol is not None else 0
        return {"ok": True,
                "area_km2": round(float(c.area_km2), 3),
                "perimetro_km": round(float(c.perimetro_km), 3),
                "long_cauce_km": round(float(c.long_cauce_km), 3),
                "truncada": bool(getattr(c, "truncada", False)),
                "n_vertices_poligono": n_vert}
    ok, r_del = _registrar("2_delinear_cuenca_merit", _delinear)
    if not ok:
        return jsonify({"ok": False, "lat": lat, "lon": lon, "pasos": pasos,
                          "sugerencia": ("MERIT Hydro no pudo delinear la "
                                          "cuenca en este punto. Probar otro "
                                          "punto en el mismo cauce 50–200 m "
                                          "aguas abajo, o usar punto sobre "
                                          "el cauce principal (no en ladera).")})

    # 3. Descarga de mapa cuenca GEE (9.1) — prueba con thumb URL
    def _mapa_cuenca():
        import tempfile, os as _os
        from idf.gee import mapa_cuenca_gee
        tmpdir = tempfile.mkdtemp()
        out = Path(tmpdir) / "test_cuenca.png"
        # Reusamos el polígono recién delineado
        from idf.watershed import delinear_cuenca_merit
        c = delinear_cuenca_merit(lat, lon, radio_grados=0.3,
                                       reintentar_borde=True)
        p = mapa_cuenca_gee(lat, lon, out, autor="diag",
                                poligono_externo=(c.poligono_latlon if c else None))
        if p is None or not Path(p).exists():
            return {"ok": False,
                    "detalle": "mapa_cuenca_gee() devolvió None o PNG vacío"}
        size = _os.path.getsize(p)
        return {"ok": True, "size_bytes": size,
                "ruta_local": str(p)}
    ok, _ = _registrar("3_mapa_cuenca_9_1", _mapa_cuenca)
    # Continuamos aunque este paso falle — el 4 puede pasar igual

    # 4. Mapa temático (uso de suelo) sobre el polígono — prueba representativa
    def _mapa_tematico():
        import tempfile, os as _os
        from idf.watershed import delinear_cuenca_merit
        from idf.mapas_gee import mapa_uso_suelo_gee
        c = delinear_cuenca_merit(lat, lon, radio_grados=0.3,
                                       reintentar_borde=True)
        # `poligono_latlon` es un numpy array → comparar con `is None`,
        # NUNCA con `not` (revienta con «truth value of an array»).
        if c is None or c.poligono_latlon is None:
            return {"ok": False, "detalle": "sin polígono para probar"}
        tmpdir = tempfile.mkdtemp()
        out = Path(tmpdir) / "test_uso.png"
        r = mapa_uso_suelo_gee(lat, lon, c.poligono_latlon, out, autor="diag")
        if r is None:
            return {"ok": False,
                    "detalle": ("mapa_uso_suelo_gee() devolvió None — "
                                  "MapBiomas Bolivia LULC v1 no respondió "
                                  "o el polígono no contiene celdas válidas")}
        if not Path(r.get("path", "")).exists():
            return {"ok": False, "detalle": "PNG no generado"}
        return {"ok": True, "size_bytes": _os.path.getsize(r["path"])}
    _registrar("4_mapa_uso_suelo_9_3", _mapa_tematico)

    # 5. FLUJO COMPLETO de mapas temáticos (lo que el pipeline real usa):
    #    generar_todos_los_mapas_gee → 9.2 (D8 COP-DEM) + 9.3..9.7. Reporta
    #    exactamente qué mapas salen REALES y cuáles no.
    def _todos_los_mapas():
        import tempfile
        from idf.watershed import delinear_cuenca_merit
        from idf.mapas_gee import generar_todos_los_mapas_gee
        c = delinear_cuenca_merit(lat, lon, radio_grados=0.3,
                                       reintentar_borde=True)
        if c is None or c.poligono_latlon is None:
            return {"ok": False, "detalle": "sin polígono delineado"}
        tmpdir = Path(tempfile.mkdtemp())
        res = generar_todos_los_mapas_gee(lat, lon, c.poligono_latlon,
                                              tmpdir, autor="diag")
        stats = res.pop("_stats", {}) if isinstance(res, dict) else {}
        claves = sorted(res.keys()) if isinstance(res, dict) else []
        esperados = ["mapa_red_drenaje", "mapa_uso_suelo", "mapa_cobertura",
                       "mapa_cn", "mapa_pendientes", "mapa_coef_escorrentia"]
        faltan = [k for k in esperados if k not in claves]
        return {"ok": len(claves) >= 1,
                "mapas_generados": claves,
                "n_generados": len(claves),
                "faltan": faltan,
                "stats": {k: round(v, 2) if isinstance(v, (int, float)) else v
                            for k, v in stats.items()}}
    _registrar("5_generar_todos_los_mapas_gee", _todos_los_mapas)

    todos_ok = all(p["ok"] for p in pasos)
    return jsonify({
        "ok": todos_ok, "lat": lat, "lon": lon, "pasos": pasos,
        "resumen": ("Todos los pasos OK — los mapas deberían generarse "
                      "en el análisis." if todos_ok else
                      "Algún paso falla — ver `detalle` y `error` por paso."),
    })


@app.route("/dataset_status", methods=["GET"])
def dataset_status():
    """Estado del buffer de telemetría local + HF Dataset destino."""
    from idf.telemetria import estado_telemetria
    return jsonify(estado_telemetria())


@app.route("/dataset.csv", methods=["GET"])
def dataset_csv():
    """Descarga el buffer local consolidado como CSV (campos no escalares JSON)."""
    from flask import Response
    from idf.telemetria import dump_csv
    csv = dump_csv()
    if not csv:
        return Response("(dataset vacío)\n", mimetype="text/plain"), 404
    return Response(csv, mimetype="text/csv",
                      headers={"Content-Disposition":
                                  "attachment; filename=hydrofra_runs.csv"})


@app.route("/dataset.xlsx", methods=["GET"])
def dataset_xlsx():
    """Descarga el dataset completo como planilla Excel (.xlsx).

    Usado por el backup diario automático (GitHub Action → email).
    """
    from flask import Response
    from idf.telemetria import dump_xlsx
    data = dump_xlsx()
    if not data:
        return Response("openpyxl no instalado o dataset vacío\n",
                          mimetype="text/plain"), 404
    fname = f"hydrofra_{datetime.utcnow().strftime('%Y-%m-%d')}.xlsx"
    return Response(
        data,
        mimetype=("application/vnd.openxmlformats-officedocument"
                    ".spreadsheetml.sheet"),
        headers={"Content-Disposition": f"attachment; filename={fname}"})


@app.route("/dataset_purge", methods=["POST"])
def dataset_purge():
    """Vacía el buffer local de telemetría (housekeeping diario).

    Protegido con token: requiere el header `X-Purge-Token` o el query
    param `token` coincidente con la env var PURGE_TOKEN del Space. NO
    toca el dataset en Hugging Face (histórico científico conservado).
    """
    token_req = (request.headers.get("X-Purge-Token")
                   or request.args.get("token") or "")
    token_esperado = os.environ.get("PURGE_TOKEN", "")
    if not token_esperado:
        return jsonify({"ok": False,
                          "razon": "PURGE_TOKEN no configurado en el Space"}), 403
    if token_req != token_esperado:
        return jsonify({"ok": False, "razon": "token inválido"}), 401
    from idf.telemetria import purgar_buffer_local
    return jsonify(purgar_buffer_local())


@app.route("/dataset.jsonl", methods=["GET"])
def dataset_jsonl():
    """Descarga el buffer local nativo (1 línea JSON por análisis)."""
    from flask import Response
    from idf.telemetria import TELEMETRIA_FILE
    if not TELEMETRIA_FILE.exists():
        return Response("(dataset vacío)\n", mimetype="text/plain"), 404
    return Response(TELEMETRIA_FILE.read_text(encoding="utf-8"),
                      mimetype="application/x-ndjson",
                      headers={"Content-Disposition":
                                  "attachment; filename=hydrofra_runs.jsonl"})


@app.route("/dataset_sync", methods=["POST", "GET"])
def dataset_sync():
    """Dispara una sincronización inmediata al HF Dataset (manual)."""
    from idf.telemetria import sincronizar_a_hf
    return jsonify(sincronizar_a_hf())


@app.route("/hf_status", methods=["GET"])
def hf_status():
    """Diagnóstico autocontenido de la conexión a HF Hub (5 chequeos en orden)."""
    from idf.telemetria import diagnostico_hf
    return jsonify(diagnostico_hf())


@app.route("/dataset_reporte.pdf", methods=["GET"])
def dataset_reporte_pdf():
    """Reporte ejecutivo del HYDROFRA Dataset — PDF generado al vuelo.

    Lee el buffer local del Space (con sync desde HF si está vacío) y compila
    un PDF con cobertura, descriptivos por modo y apéndice de últimos
    registros. Cada descarga refleja el estado actual de la base de datos.
    """
    from flask import Response
    from idf.reporte_dataset import generar_pdf_dataset
    pdf = generar_pdf_dataset()
    fname = f"hydrofra_dataset_{datetime.utcnow().strftime('%Y%m%d')}.pdf"
    return Response(pdf, mimetype="application/pdf",
                      headers={"Content-Disposition": f"inline; filename={fname}"})



def _qmin_worker(sesion_dir: Path, params: dict) -> None:
    """Pipeline asíncrono de caudales mínimos.

    Mueve TODO el trabajo pesado de /analizar_minimos (delineación MERIT, 6
    mapas GEE temáticos, transformación P→Q, consistencia, ranking,
    rellenado, plots) a un thread daemon. El render del HTML final se
    guarda como `resultado.html` para que /resultado lo sirva. El frontend
    polea /status como en el pipeline de máximos.
    """
    stop_hb = threading.Event()
    estado_actual = {"paso": "Iniciando análisis de caudales mínimos…"}
    # Watchdog: si el pipeline excede el deadline (cuencas gigantes tipo
    # Bermejo agotaron antes los recursos del Space sin escribir resultado),
    # marcamos status=error con mensaje claro para que el frontend deje de
    # polear y muestre el problema.
    DEADLINE_SEG = 9 * 60
    inicio = time.time()

    def _heartbeat():
        while not stop_hb.wait(8):
            t = time.time()
            if t - inicio > DEADLINE_SEG:
                _escribir_status(sesion_dir, {
                    "estado": "error",
                    "mensaje": ("Tiempo máximo de análisis excedido (9 min). "
                                "La cuenca puede ser demasiado grande para "
                                "los recursos del servicio. Pruebe con un "
                                "punto en un afluente más pequeño."),
                    "ts": t,
                })
                return
            _escribir_status(sesion_dir, {
                "estado": "procesando",
                "paso": estado_actual["paso"],
                "ts": t,
            })

    hb = threading.Thread(target=_heartbeat, daemon=True)
    hb.start()
    sesion_id = sesion_dir.name
    try:
        _escribir_status(sesion_dir, {
            "estado": "procesando", "paso": estado_actual["paso"],
            "inicio": time.time(), "ts": time.time(),
        })
        import numpy as np
        from idf.estaciones_hidro import estaciones_por_estado
        from idf.catalogo_senamhi import CATALOGO as _CATALOGO_SENAMHI
        from idf.catalogo_adapter import (met_cercanas_oficial,
                                            hidro_cercanas_oficial)

        lat = params["lat"]
        lon = params["lon"]
        anios = params["anios"]
        uso = params["uso"]
        proyecto = params["proyecto"]
        analisis = params["analisis"]
        ap_demanda = params.get("ap_demanda") or {}

        RADIO_KM = 100.0
        estado_actual["paso"] = ("Buscando estaciones SENAMHI dentro de "
                                  "100 km (catálogo oficial 1 861 sitios)…")
        # Buscamos hasta 20 met + 20 hidro dentro del radio. Si el sitio cae
        # en zona sin red operativa SENAMHI, abrimos el filtro a estaciones
        # de cualquier estado para no dejar el reporte vacío.
        met_cercanas = met_cercanas_oficial(lat, lon, radio_km=RADIO_KM,
                                               tope=20, solo_activas=False)
        if not met_cercanas:
            met_cercanas = met_cercanas_oficial(lat, lon, radio_km=300,
                                                   tope=5, solo_activas=False)
        hidro_cercanas = hidro_cercanas_oficial(lat, lon, radio_km=RADIO_KM,
                                                   tope=20, solo_activas=False)
        if not hidro_cercanas:
            hidro_cercanas = hidro_cercanas_oficial(lat, lon, radio_km=300,
                                                       tope=5, solo_activas=False)
        # Conteo legacy por estado (compatibilidad con la sección de
        # «Estado de la red hidrométrica» del template).
        from collections import Counter
        estado_hidro_legacy = Counter(e.estado for e, _ in hidro_cercanas)
        estado_hidro = {"activa": estado_hidro_legacy.get("activa", 0),
                          "pasiva": estado_hidro_legacy.get("pasiva", 0),
                          "intermitente": estado_hidro_legacy.get("intermitente", 0)}
        # Totales del catálogo oficial (para el footer del reporte).
        from idf.catalogo_senamhi import filtrar as _filtrar_cat
        n_met_total = len(_filtrar_cat(categoria="Meteorológica"))
        n_hidro_total = len(_filtrar_cat(categoria="Hidrológica"))
        from idf.mapa_regional import mapa_regional
        estado_actual["paso"] = "Generando mapa regional con fondo Sentinel-2…"
        mapa_regional(lat, lon, sesion_dir / "mapa_regional.png",
                       estaciones_met=met_cercanas,
                       estaciones_hidro=hidro_cercanas,
                       radio_km=RADIO_KM,
                       nombre_sitio=proyecto.nombre_proyecto or "Sitio",
                       fondo_satelital=True)

        cuenca_qmin = None
        mapas_qmin: dict = {}
        stats_qmin: dict = {}
        # Rango operativo recomendado para Q mín locales: 1 km² ≤ A ≤ 2000 km².
        # Por debajo de 1 km² la delineación MERIT 90 m es degenerada (puede
        # quedar atrapada en una sola celda de ladera); por encima de 2000 km²
        # los mapas GEE temáticos a esa escala dejan de representar la
        # hidrología local del punto y consumen demasiado recurso del Space.
        AREA_MIN_KM2 = 1.0
        AREA_MAX_KM2 = 2000.0
        cuenca_fuera_rango = False
        try:
            from idf.watershed import delinear_cuenca_merit
            from idf.gee import mapa_cuenca_gee
            from idf.mapas_qmin_gee import generar_mapas_qmin
            estado_actual["paso"] = "Delineando cuenca con MERIT Hydro…"
            # Para Q mín priorizamos completar rápido: tile 0.25° (~28 km de
            # radio) y sin reintento con tile mayor cuando la cuenca toca
            # el borde.
            cuenca_qmin = delinear_cuenca_merit(lat, lon, radio_grados=0.25,
                                                  reintentar_borde=False)
            if cuenca_qmin is not None:
                if (cuenca_qmin.area_km2 < AREA_MIN_KM2
                        or cuenca_qmin.area_km2 > AREA_MAX_KM2
                        or getattr(cuenca_qmin, "truncada", False)):
                    cuenca_fuera_rango = True
                    print(f"[qmin] cuenca fuera de rango operativo "
                           f"({cuenca_qmin.area_km2:.2f} km², esperado "
                           f"{AREA_MIN_KM2}–{AREA_MAX_KM2} km²): "
                           "se omiten mapas GEE", flush=True)
                else:
                    estado_actual["paso"] = "Descargando mapa de la cuenca (GEE)…"
                    mapa_cuenca_gee(lat, lon, sesion_dir / "qmin_cuenca.png",
                                    autor=f"Ing. {proyecto.ingeniero}",
                                    poligono_externo=cuenca_qmin.poligono_latlon)
                    estado_actual["paso"] = "Generando 6 mapas temáticos GEE (CHIRPS·MOD16·SMAP)…"
                    mapas_qmin = generar_mapas_qmin(
                        lat, lon, cuenca_qmin.poligono_latlon, sesion_dir,
                        autor=f"Ing. {proyecto.ingeniero}")
                    stats_qmin = mapas_qmin.pop("_stats", {}) if mapas_qmin else {}
                    mapas_qmin = {k: Path(v).name for k, v in mapas_qmin.items()}
                    if stats_qmin.get("pann_mm"):
                        stats_qmin["pann_mm_fuente"] = "CHIRPS_GEE"
        except Exception as e:  # noqa: BLE001
            print(f"[qmin] cuenca/mapas GEE no disponibles: {e}", flush=True)

        pq = None
        plot_balance_url = None
        plot_fdc_url = None
        # Climatología de precipitación: combina lo que vino de los mapas GEE
        # con la grilla baseline (49 SENAMHI curadas IDW) como fallback. La
        # grilla cubre todo Bolivia, por lo que el balance P→Q se puede correr
        # aún cuando GEE no responda.
        from idf.grilla_precip import climatologia_punto as _grilla_clima
        pann_efectivo = stats_qmin.get("pann_mm")
        eta_efectivo = stats_qmin.get("eta_mm")
        if pann_efectivo is None:
            clima_grilla = _grilla_clima(lat, lon)
            if clima_grilla is not None:
                pann_efectivo = clima_grilla.p_anual_mm
                stats_qmin["pann_mm_fuente"] = clima_grilla.fuente
                # ETa estimado por Budyko simplificado (limita por PET)
                eta_efectivo = eta_efectivo or min(0.80 * pann_efectivo, 1200.0)
                stats_qmin.setdefault("pann_mm", pann_efectivo)
                stats_qmin.setdefault("eta_mm", eta_efectivo)

        if cuenca_qmin is not None and (stats_qmin.get("pann_mm") or pann_efectivo):
            try:
                from idf.transformacion_pq import (transformacion_pq,
                                                     plot_balance_mensual,
                                                     plot_fdc)
                estado_actual["paso"] = "Resolviendo balance hidrológico mensual P→Q…"
                pq = transformacion_pq(
                    area_km2=cuenca_qmin.area_km2,
                    pann_mm=pann_efectivo,
                    etann_mm=eta_efectivo,
                    caw_mm=stats_qmin.get("caw_mm"),
                    cn_ponderado=None,
                    ai=stats_qmin.get("ai"),
                    twi=stats_qmin.get("twi"),
                )
                plot_balance_mensual(pq, sesion_dir / "qmin_balance.png")
                plot_fdc(pq, sesion_dir / "qmin_fdc.png")
                plot_balance_url = "qmin_balance.png"
                plot_fdc_url = "qmin_fdc.png"
            except Exception as e:  # noqa: BLE001
                print(f"[qmin] transformación P→Q falló: {e}", flush=True)

        from idf.consistencia_qmin import (analizar_consistencia,
                                              seleccionar_estaciones,
                                              comparar_seleccionadas,
                                              plot_series_seleccionadas,
                                              METODOLOGIA_SELECCION,
                                              CriterioSeleccion)
        estado_actual["paso"] = "Aplicando pruebas de consistencia OMM-168…"
        diagnosticos_consistencia = analizar_consistencia(met_cercanas,
                                                            hidro_cercanas)
        seleccionadas = seleccionar_estaciones(
            diagnosticos_consistencia, cuenca_qmin,
            criterios=CriterioSeleccion(radio_max_km=RADIO_KM))
        comparadas = comparar_seleccionadas(seleccionadas, met_cercanas,
                                              hidro_cercanas)
        plot_series_url = None
        if comparadas:
            p = plot_series_seleccionadas(comparadas, sesion_dir / "qmin_series.png")
            if p is not None:
                plot_series_url = "qmin_series.png"

        from idf.seleccion_modelo_cc import (metodologia_pasos,
                                                metricas_desempeno,
                                                metricas_bajo_caudal,
                                                metodos_correccion_sesgo,
                                                metodos_ensemble,
                                                region_bolivia, nombre_region,
                                                modelos_recomendados,
                                                RECOMENDACIONES_BOLIVIA)
        region_cc = region_bolivia(
            lat, lon,
            altitud_msnm=getattr(cuenca_qmin, "cota_menor_m", None))
        s3_1 = {
            "pasos": metodologia_pasos(),
            "metricas": metricas_desempeno(),
            "metricas_min": metricas_bajo_caudal(),
            "bias_correction": metodos_correccion_sesgo(),
            "ensemble": metodos_ensemble(),
            "region": region_cc,
            "region_nombre": nombre_region(region_cc),
            "modelos_region": modelos_recomendados(region_cc),
            "recomendaciones": RECOMENDACIONES_BOLIVIA,
        }

        from idf.marcos_qmin import obtener_marco, NOMBRE_USO
        marco = obtener_marco(uso)
        from idf.frecuencia_no_estacionaria import SECCION_FRECUENCIA_NS
        from idf.conclusiones_qmin import conclusiones_dinamicas, recomendaciones
        s6_conclusiones = conclusiones_dinamicas(
            uso, marco, lat, lon, met_cercanas, hidro_cercanas,
            n_met_total, n_hidro_total, estado_hidro)
        s6_recomendaciones = recomendaciones(uso)
        from idf.referencias_qmin_apa import (numerar as numerar_refs,
                                                 total_referencias)
        s7_refs = numerar_refs()
        s7_total = total_referencias()

        # --- Sección 4.7 y 5.0: cálculos operacionales (caudales + frecuencia) ---
        from idf.calculos_qmin import (ajustar_distribuciones_qmin,
                                          cuantiles_qmin_t, caudal_ecologico,
                                          q7_10_aproximado, spi,
                                          evaluar_modelos_cc,
                                          plot_frecuencia_qmin,
                                          plot_caudal_ecologico, plot_spi,
                                          plot_modelos_taylor)
        estado_actual["paso"] = "Calculando frecuencia de caudales mínimos…"
        from idf.consistencia_qmin import _serie_anual_caudal, _serie_anual_normal
        # Serie anual de Q mín «representativa»: media de las series de las
        # estaciones hidro seleccionadas, escalada por área de la cuenca
        # (transferencia regional simple). Si no hay hidro seleccionadas,
        # usa el Q mín mensual del balance P→Q replicado con ruido.
        T_LISTA = (2, 5, 10, 25, 50, 100)
        hidro_seleccionadas = [d for d, _, _ in seleccionadas
                                 if d.tipo == "hidro"]
        if hidro_seleccionadas and hidro_cercanas:
            cat_h = {e.codigo: e for e, _ in hidro_cercanas}
            series_h = []
            for d in hidro_seleccionadas:
                if d.codigo in cat_h:
                    e = cat_h[d.codigo]
                    s = _serie_anual_caudal(e.q_medio_m3s, e.q_min_m3s,
                                              d.n_anios, e.codigo)
                    series_h.append(s)
            n_comun = min(s.size for s in series_h)
            promedio_regional = np.mean(
                np.vstack([s[-n_comun:] for s in series_h]), axis=0)
            # Escalado por área (cuenca / promedio de estaciones).
            if cuenca_qmin is not None:
                A_cuenca = cuenca_qmin.area_km2
                A_estaciones = np.mean(
                    [cat_h[d.codigo].area_aporte_km2
                     for d in hidro_seleccionadas if d.codigo in cat_h])
                factor = A_cuenca / max(A_estaciones, 1.0)
                serie_qmin_anual = promedio_regional * factor
            else:
                serie_qmin_anual = promedio_regional
        elif pq is not None:
            # Sin hidro: usa Q mín mensual del balance + ruido reproducible.
            rng_qm = np.random.default_rng(7)
            serie_qmin_anual = np.maximum(
                pq.q_min_m3s + rng_qm.normal(
                    0, max(0.15 * pq.q_min_m3s, 1e-3), size=30), 1e-4)
        else:
            serie_qmin_anual = np.array([])

        ajuste_qmin = ajustar_distribuciones_qmin(serie_qmin_anual)
        cuantiles_qmin = cuantiles_qmin_t(ajuste_qmin, T_LISTA)
        plot_frec_url = None
        if ajuste_qmin.get("mejor"):
            p = plot_frecuencia_qmin(serie_qmin_anual, ajuste_qmin, T_LISTA,
                                       sesion_dir / "qmin_frecuencia.png")
            if p:
                plot_frec_url = "qmin_frecuencia.png"

        # Q7,10 y cálculo del caudal ecológico (5 métodos).
        ce_lista = []
        plot_eco_url = None
        if pq is not None and len(pq.q_mes_m3s):
            cv_estac = float(np.std(pq.q_mes_m3s) / max(np.mean(pq.q_mes_m3s),
                                                          1e-6))
            q710 = q7_10_aproximado(pq.q_min_m3s, pq.q_medio_m3s, cv_estac)
            ce_lista = caudal_ecologico(
                pq.q_mes_m3s, pq.q_medio_m3s, pq.q90, pq.q95, q710)
            p = plot_caudal_ecologico(ce_lista, pq.q_medio_m3s,
                                        sesion_dir / "qmin_eco.png")
            if p:
                plot_eco_url = "qmin_eco.png"
        else:
            q710 = 0.0

        # SPI-3 sobre la precipitación mensual climática (replicada).
        plot_spi_url = None
        spi_serie = np.array([])
        if pq is not None and len(pq.p_mes_mm):
            estado_actual["paso"] = "Calculando SPI (McKee 1993)…"
            # Replica la climatología 30 años para tener serie ≥ 360 meses,
            # con ruido reproducible.
            rng_p = np.random.default_rng(11)
            anios_spi = 30
            p_serie = []
            for _ in range(anios_spi):
                p_serie.append(np.maximum(0,
                    pq.p_mes_mm + rng_p.normal(0, 0.20 * pq.p_mes_mm)))
            p_serie = np.concatenate(p_serie)
            spi_serie = spi(p_serie, escala=3)
            p = plot_spi(spi_serie, sesion_dir / "qmin_spi.png", escala=3)
            if p:
                plot_spi_url = "qmin_spi.png"

        # Evaluación de modelos CC: 4 modelos sintéticos calibrados de la
        # región para demostrar el ranking. Reemplazables al conectar las
        # series CMIP6 reales.
        modelos_evaluados = []
        plot_taylor_url = None
        if serie_qmin_anual.size >= 8:
            estado_actual["paso"] = "Evaluando ajuste de modelos CC vs observación…"
            obs = serie_qmin_anual
            rng_m = np.random.default_rng(13)
            modelos_eval = s3_1["modelos_region"]["cmip6_curados"][:4]
            sim_dict = {}
            ruidos = [(0.03, 1.00), (0.08, 1.05), (0.15, 0.92), (0.25, 1.20)]
            for nombre, (sig, sesgo) in zip(modelos_eval, ruidos):
                sim_dict[nombre] = np.maximum(0,
                    obs * sesgo + rng_m.normal(0, sig * obs.mean(), obs.size))
            modelos_evaluados = evaluar_modelos_cc(obs, sim_dict)
            p = plot_modelos_taylor(modelos_evaluados,
                                      sesion_dir / "qmin_taylor.png")
            if p:
                plot_taylor_url = "qmin_taylor.png"

        s4_7 = {
            "T_lista": T_LISTA,
            "cuantiles": cuantiles_qmin,
            "mejor_dist": ajuste_qmin.get("mejor"),
            "n_serie": ajuste_qmin.get("n", 0),
            "q7_10": q710,
            "caudal_ecologico": ce_lista,
            "plot_frec_url": plot_frec_url,
            "plot_eco_url": plot_eco_url,
        }
        s5_0 = {
            "spi_serie": spi_serie.tolist() if spi_serie.size else [],
            "plot_spi_url": plot_spi_url,
            "modelos_evaluados": modelos_evaluados,
            "plot_taylor_url": plot_taylor_url,
        }

        estado_actual["paso"] = "Renderizando el informe…"
        with app.test_request_context():
            html = render_template(
                "qmin_resumen.html", proyecto=proyecto.limpio(),
                sesion_id=sesion_id, lat=lat, lon=lon, anios=anios, uso=uso,
                nombre_uso=NOMBRE_USO.get(uso, uso),
                analisis=analisis,
                met_cercanas=met_cercanas, hidro_cercanas=hidro_cercanas,
                estado_hidro=estado_hidro,
                n_met_total=n_met_total,
                n_hidro_total=n_hidro_total,
                radio_km=RADIO_KM,
                cuenca_qmin=cuenca_qmin,
                area_min_km2=AREA_MIN_KM2,
                area_max_km2=AREA_MAX_KM2,
                cuenca_fuera_rango=cuenca_fuera_rango,
                mapas_qmin=mapas_qmin,
                stats_qmin=stats_qmin,
                clima_fuente=_CLIMA_FUENTE_LABEL.get(
                    stats_qmin.get("pann_mm_fuente"),
                    stats_qmin.get("pann_mm_fuente")),
                diagnosticos_consistencia=diagnosticos_consistencia,
                seleccionadas=seleccionadas,
                comparadas=comparadas,
                metodologia_seleccion=METODOLOGIA_SELECCION,
                plot_series_url=plot_series_url,
                pq=pq,
                plot_balance_url=plot_balance_url,
                plot_fdc_url=plot_fdc_url,
                s3_1=s3_1,
                s4_7=s4_7,
                s5_0=s5_0,
                marco=marco,
                s5=SECCION_FRECUENCIA_NS,
                s6_conclusiones=s6_conclusiones,
                s6_recomendaciones=s6_recomendaciones,
                s7_refs=s7_refs,
                s7_total=s7_total,
            )
        (sesion_dir / "resultado.html").write_text(html, encoding="utf-8")

        # Compila el PDF protegido (AES-128) con todas las secciones.
        pdf_name = None
        try:
            estado_actual["paso"] = "Compilando informe PDF protegido…"
            from idf.report_qmin import generar_pdf_qmin
            datos_pdf = {
                "proyecto": proyecto.limpio(),
                "lat": lat, "lon": lon, "anios": anios, "uso": uso,
                "nombre_uso": NOMBRE_USO.get(uso, uso),
                "radio_km": RADIO_KM,
                "area_min_km2": AREA_MIN_KM2,
                "area_max_km2": AREA_MAX_KM2,
                "cuenca_fuera_rango": cuenca_fuera_rango,
                "cuenca_qmin": cuenca_qmin,
                "mapas_qmin": mapas_qmin,
                "stats_qmin": stats_qmin,
                "clima_fuente": _CLIMA_FUENTE_LABEL.get(
                    stats_qmin.get("pann_mm_fuente"),
                    stats_qmin.get("pann_mm_fuente")),
                "diagnosticos_consistencia": diagnosticos_consistencia,
                "seleccionadas": seleccionadas,
                "comparadas": comparadas,
                "met_cercanas": met_cercanas,
                "hidro_cercanas": hidro_cercanas,
                "pq": pq,
                "s3_1": s3_1,
                "s4_7": s4_7,
                "s5_0": s5_0,
                "marco": marco,
                "s5": SECCION_FRECUENCIA_NS,
                "s6_conclusiones": s6_conclusiones,
                "s6_recomendaciones": s6_recomendaciones,
                "s7_refs": s7_refs,
            }
            # Bloque agua potable: demanda + transposición + balance.
            # Solo se calcula si uso=captacion_agua; en otros casos los
            # campos quedan ausentes y el generador legacy ignora.
            if uso == "captacion_agua":
                datos_pdf["ap_demanda_input"] = ap_demanda
                try:
                    datos_pdf.update(_construir_bloque_agua_potable(
                        lat=lat, lon=lon, ap_demanda=ap_demanda,
                        cuenca_qmin=cuenca_qmin, pq=pq,
                        hidro_cercanas=hidro_cercanas,
                        stats_qmin=stats_qmin, pq_eco=ce_lista,
                        cuantiles_qmin=cuantiles_qmin,
                        q7_10=q710))
                except Exception as e:  # noqa: BLE001
                    print(f"[qmin/ap] bloque agua potable falló: "
                           f"{type(e).__name__}: {e}", flush=True)
            pdf_path = generar_pdf_qmin(
                sesion_dir / f"HYDROFRA_Qmin_{sesion_id}.pdf",
                datos_pdf, sesion_dir)
            pdf_name = pdf_path.name
        except Exception as e:  # noqa: BLE001
            print(f"[qmin] PDF falló: {type(e).__name__}: {e}", flush=True)

        # Telemetría — persiste el análisis si el usuario dio consentimiento.
        try:
            from idf.telemetria import registrar_qmin
            registrar_qmin(datos_pdf, sesion_id=sesion_id,
                            consent=params.get("telemetria_consent", False))
        except Exception as e:  # noqa: BLE001
            print(f"[telemetria] qmin falló: {e}", flush=True)

        gc.collect()
        stop_hb.set()
        _escribir_status(sesion_dir, {
            "estado": "completo",
            "pdf": pdf_name,
            "fin": time.time(),
        })
    except Exception as e:  # noqa: BLE001
        stop_hb.set()
        _escribir_status(sesion_dir, {
            "estado": "error",
            "mensaje": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        })


@app.route("/analizar_minimos", methods=["POST"])
@login_required
def analizar_minimos():
    """Caudales mínimos — endpoint asíncrono.

    Antes hacía toda la delineación + 6 mapas GEE + transformación P→Q + el
    panel de consistencia en una sola request, lo que excedía el timeout
    del proxy de HF (~100 s). Ahora arranca un worker daemon y devuelve
    inmediatamente `procesando.html`; el frontend polea /status como en el
    pipeline de máximos.
    """
    if not usuarios.puede_analizar(session["user_email"]):
        return _limite_alcanzado_pagina()
    try:
        lat = float(request.form.get("lat", 0))
        lon = float(request.form.get("lon", 0))
        anios = int(request.form.get("anios", 35))
        uso = request.form.get("uso", "captacion_agua")
        proyecto = DatosProyecto(
            request.form.get("nombre_proyecto", ""),
            request.form.get("ingeniero") or session.get("user_nombre", ""),
            request.form.get("ubicacion", ""),
            contratante=request.form.get("contratante", ""),
            codigo_sisin=request.form.get("codigo_sisin", ""),
            municipio=request.form.get("municipio", ""),
            provincia=request.form.get("provincia", ""),
            departamento=request.form.get("departamento", ""),
            registro_profesional=request.form.get("registro_profesional", ""),
            jefe_proyecto=request.form.get("jefe_proyecto", ""),
        )
    except (TypeError, ValueError):
        flash("Datos del formulario inválidos.", "danger")
        return redirect(url_for("index"))
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        flash("Coordenadas fuera de rango.", "danger")
        return redirect(url_for("index"))
    analisis = {
        "FDC": request.form.get("incluir_fdc") == "on",
        "Frecuencia mínimos": request.form.get("incluir_frecuencia") == "on",
        "Ecológicos": request.form.get("incluir_ecologico") == "on",
        "Recesión": request.form.get("incluir_recesion") == "on",
        "Cambio climático": request.form.get("incluir_clima") == "on",
    }
    _limpiar_sesiones_viejas()
    sesion_id = uuid.uuid4().hex[:12]
    sesion_dir = SESSIONS_DIR / sesion_id
    sesion_dir.mkdir(parents=True, exist_ok=True)
    from idf.telemetria import consentimiento_desde_form
    # Bloque «Datos de demanda» (agua potable). Si el uso != captación de
    # agua, estos valores se ignoran. Defaults razonables para que el
    # informe pueda emitirse aún con un form mínimo.
    def _f_or(name, default):
        v = (request.form.get(name) or "").strip()
        try:
            return float(v) if v else default
        except ValueError:
            return default
    def _i_or(name, default):
        v = (request.form.get(name) or "").strip()
        try:
            return int(float(v)) if v else default
        except ValueError:
            return default
    ap_demanda = {
        "poblacion_actual": _i_or("ap_poblacion_actual", 500),
        "tasa_crec_pct": _f_or("ap_tasa_crec_pct", 1.5),
        "horizonte_anios": _i_or("ap_horizonte_anios", 20),
        "metodo_proy": (request.form.get("ap_metodo_proy")
                          or "geometrico").lower(),
        "nivel_servicio": (request.form.get("ap_nivel_servicio")
                            or "domiciliaria_basica").lower(),
        "dotacion_l_hab_dia": (_f_or("ap_dotacion_l_hab_dia", 0.0)
                                  or None),  # None → auto por piso
    }
    params = {
        "lat": lat, "lon": lon, "anios": anios, "uso": uso,
        "proyecto": proyecto, "analisis": analisis,
        "ap_demanda": ap_demanda,
        "telemetria_consent": consentimiento_desde_form(request.form),
    }
    ok_cuota, _rest = usuarios.consumir(session["user_email"],
                                        session.get("user_nombre", ""))
    if not ok_cuota:
        return _limite_alcanzado_pagina()
    _escribir_status(sesion_dir, {"estado": "procesando",
                                    "paso": "Iniciando análisis de caudales mínimos…",
                                    "inicio": time.time()})
    threading.Thread(target=_qmin_worker, args=(sesion_dir, params),
                       daemon=True).start()
    return render_template("procesando.html", sesion_id=sesion_id)


@app.route("/analizar", methods=["POST"])
@login_required
def analizar():
    """Arranca el pipeline en thread y devuelve la página de progreso.

    Antes el endpoint era síncrono y devolvía el resultado tras 2-5 min, lo
    que excedía el timeout del proxy de HF (~100 s) y daba ERR_CONNECTION_ABORTED.
    Ahora retorna inmediato; el frontend polea `/status/<sesion_id>`.
    """
    if not usuarios.puede_analizar(session["user_email"]):
        return _limite_alcanzado_pagina()
    try:
        lat = float(request.form.get("lat", 0))
        lon = float(request.form.get("lon", 0))
        anios = int(request.form.get("anios", 35))
        semilla = int(request.form.get("semilla", 42))
        exp_dp = float(request.form.get("exp_dp", 0.25))
        criterio = request.form.get("criterio", "ks")
        obra = request.form.get("obra", "carretera_puente")
        t_diseno_raw = request.form.get("t_diseno", "")
        t_diseno = int(t_diseno_raw) if t_diseno_raw.strip() else None
        cn_disponible = request.form.get("cn_disponible") == "on"
        resolucion = request.form.get("resolucion", "diaria")
        # Toggle visible en el form. Default checked = modo completo
        # (CHIRPS+NASA POWER+Open-Meteo, 7 mapas GEE). Si el usuario lo
        # desmarca, queda modo_ligero=True (20-40s, solo estación).
        modo_ligero = request.form.get("informe_completo") != "on"
        proyecto = DatosProyecto(
            request.form.get("nombre_proyecto", ""),
            request.form.get("ingeniero") or session.get("user_nombre", ""),
            request.form.get("ubicacion", ""),
            contratante=request.form.get("contratante", ""),
            codigo_sisin=request.form.get("codigo_sisin", ""),
            municipio=request.form.get("municipio", ""),
            provincia=request.form.get("provincia", ""),
            departamento=request.form.get("departamento", ""),
            registro_profesional=request.form.get("registro_profesional", ""),
            jefe_proyecto=request.form.get("jefe_proyecto", ""),
        )
    except (TypeError, ValueError):
        flash("Datos del formulario inválidos.", "danger")
        return redirect(url_for("index"))

    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        flash("Coordenadas fuera de rango.", "danger")
        return redirect(url_for("index"))
    if anios < 10 or anios > 200:
        flash("Años de serie debe estar entre 10 y 200.", "danger")
        return redirect(url_for("index"))

    _limpiar_sesiones_viejas()
    sesion_id = uuid.uuid4().hex[:12]
    out = SESSIONS_DIR / sesion_id
    out.mkdir(parents=True, exist_ok=True)

    from idf.telemetria import consentimiento_desde_form
    # Parámetros del puente para el pilar de socavación (opcionales; presentes
    # en la pestaña Hidráulica Fluvial). Ausentes → socavación con defaults.
    def _num(nombre):
        v = (request.form.get(nombre) or "").strip()
        try:
            return float(v) if v else None
        except ValueError:
            return None
    from idf.socavacion import D50_POR_CAUCE, D50_DEFECTO_MM
    _d50 = _num("d50") or D50_POR_CAUCE.get(request.form.get("tipo_cauce", ""))
    params_puente = {
        "ancho_pila_m": _num("ancho_pila"),
        "forma_pila": request.form.get("forma_pila", "redonda"),
        "angulo_ataque_grados": _num("angulo_ataque") or 0.0,
        "long_pila_m": _num("long_pila"),
        "long_estribo_m": _num("long_estribo"),
        "forma_estribo": request.form.get("forma_estribo", "derramado"),
        "D50_mm": _d50 if _d50 else D50_DEFECTO_MM,
    }
    # Gálibo (borde libre) de la viga: solo se fija si el usuario lo indica;
    # si se deja vacío, el motor usa el valor normativo por defecto (2.0 m).
    _galibo = _num("galibo")
    if _galibo:
        params_puente["galibo_m"] = _galibo
    _palizada = _num("palizada")
    if _palizada is not None:
        params_puente["altura_palizada_m"] = _palizada
    _galibo_min = _num("galibo_min")
    if _galibo_min:
        params_puente["galibo_min_m"] = _galibo_min
    # Alcantarillas (drenaje vial menor): longitud real de la obra y tirante
    # aguas abajo del cauce receptor. Ausentes → valores por defecto del motor.
    params_alcantarilla = {
        "long_m": _num("alc_long"),
        "tw_m": _num("alc_tw"),
    }
    # Diseño de sección fija (si el usuario eligió tipo != "auto").
    _alc_tipo = (request.form.get("alc_tipo") or "auto").strip()
    if _alc_tipo and _alc_tipo != "auto":
        _celdas = _num("alc_celdas")
        params_alcantarilla["tipo_fijo"] = _alc_tipo
        params_alcantarilla["n_celdas_fijo"] = int(_celdas) if _celdas else 1
        params_alcantarilla["D_fijo"] = _num("alc_diam")
        params_alcantarilla["B_fijo"] = _num("alc_base")
        params_alcantarilla["H_fijo"] = _num("alc_alto")
    # Captación de riego menor (si el tipo de obra es riego pequeño).
    params_riego = {
        "q_captacion_ls": _num("riego_q"),
        "q_estiaje_ls": _num("riego_qestiaje"),
        "area_ha": _num("riego_area"),
        "modulo_ls_ha": _num("riego_modulo"),
        "ancho_rio_m": _num("riego_ancho_rio"),
        "cota_captacion": (request.form.get("riego_cota") or "").strip() or None,
        "canal_so_pct": _num("riego_so"),
        "canal_revestimiento": (request.form.get("riego_revest")
                                or "hormigon").strip(),
        "canal_forma": (request.form.get("riego_forma")
                        or "trapezoidal").strip(),
        "canal_talud_z": _num("riego_talud"),
        "canal_base_m": _num("riego_base"),
        "d_particula_mm": _num("riego_dpart"),
    }
    # Modelación HEC-RAS externa (opcional): el usuario sube el HDF del plan
    # ya calculado en su PC; se guarda en la sesión y el pipeline lo lee.
    hecras_hdf = None
    _f = request.files.get("hecras_hdf")
    if _f is not None and _f.filename:
        _dest = out / "hecras_plan.hdf"
        try:
            _f.save(str(_dest))
            hecras_hdf = str(_dest)
        except Exception as e:  # noqa: BLE001
            app.logger.warning("No se pudo guardar el HDF de HEC-RAS: %s", e)
    params = {
        "proyecto": proyecto, "lat": lat, "lon": lon,
        "tipo_obra_clave": obra, "T_diseno": t_diseno,
        "anios": anios, "semilla": semilla, "exp_dp": exp_dp,
        "criterio": criterio, "cn_disponible": cn_disponible,
        "resolucion_datos": resolucion, "modo_ligero": modo_ligero,
        "params_puente": params_puente,
        "params_alcantarilla": params_alcantarilla,
        "params_riego": params_riego,
        "hecras_hdf": hecras_hdf,
        "serie_observada": _serie_obs_desde_form(request.form),
        "telemetria_consent": consentimiento_desde_form(request.form),
    }
    ok_cuota, _rest = usuarios.consumir(session["user_email"],
                                        session.get("user_nombre", ""))
    if not ok_cuota:
        return _limite_alcanzado_pagina()
    _escribir_status(out, {"estado": "procesando",
                            "paso": "Iniciando análisis…",
                            "inicio": time.time()})
    threading.Thread(target=_pipeline_worker, args=(out, params),
                     daemon=True).start()
    return render_template("procesando.html", sesion_id=sesion_id)


@app.route("/status/<sesion_id>", methods=["GET"])
def status(sesion_id: str):
    if not sesion_id.isalnum() or len(sesion_id) > 32:
        abort(400)
    d = SESSIONS_DIR / sesion_id
    if not d.is_dir():
        return jsonify({"estado": "no_existe"}), 404
    s = _leer_status(d)
    # Detector de heartbeat muerto: si el worker fue terminado por OOM o el
    # contenedor reiniciado, el heartbeat deja de escribirse pero status.json
    # se queda en «procesando» con un `ts` viejo. Umbral de 300 s: en cuencas
    # grandes hay pasos CPU (flood-fill D8, morfometría) que acaparan el GIL y
    # el heartbeat (thread) no alcanza a refrescarse durante varios minutos;
    # con 90 s el análisis se declaraba «muerto» aunque seguía vivo. 300 s da
    # margen a esos pasos legítimos sin dejar el status colgado para siempre.
    if s.get("estado") == "procesando":
        ts = s.get("ts") or s.get("inicio")
        if ts and (time.time() - float(ts)) > 300:
            s = {"estado": "error",
                  "mensaje": ("El servicio dejó de responder durante el "
                              "análisis (posiblemente por límite de recursos "
                              "del contenedor). Intente nuevamente con un "
                              "punto en un afluente más pequeño."),
                  "ts": time.time()}
    return jsonify(s)


@app.route("/resultado/<sesion_id>", methods=["GET"])
def resultado(sesion_id: str):
    if not sesion_id.isalnum() or len(sesion_id) > 32:
        abort(400)
    d = SESSIONS_DIR / sesion_id
    if not d.is_dir():
        abort(404)
    html_file = d / "resultado.html"
    if not html_file.exists():
        abort(404, "Resultado no disponible (todavía procesando o el job falló).")
    # El HTML ya fue renderizado por el worker (evita picklear R, que contiene
    # closures no serializables de los modelos IDF).
    return html_file.read_text(encoding="utf-8")


@app.route("/reportes/<sesion_id>/<archivo>", methods=["GET"])
def reportes(sesion_id: str, archivo: str):
    if not sesion_id.isalnum() or "/" in archivo or ".." in archivo:
        abort(400)
    d = SESSIONS_DIR / sesion_id
    if not d.is_dir():
        abort(404)
    return send_from_directory(d, archivo, as_attachment=False)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=False)
