"""Cliente HTTP para descargar PDFs del portal SENAMHI.

Diseñado para correr **offline como batch** (típicamente desde
`scripts/scrape_bhn.py`) y NO durante una request de la webapp: el portal
SENAMHI está protegido por Cloudflare WAF que tolera mal el tráfico
automatizado masivo.

Tres niveles de cliente HTTP en orden de preferencia:

1. **curl_cffi.requests** (si está instalado): impersona el TLS fingerprint
   de Chrome 120 y suele pasar el desafío de Cloudflare sin Selenium.
   Instalación: `pip install curl_cffi`.
2. **requests** estándar con User-Agent realista (sirve cuando Cloudflare
   está en modo permisivo o cuando se ejecuta desde IP boliviana).
3. **urllib.request** como último recurso (solo para tests offline).

Cada descarga registra metadata (SHA-256, content-length, content-type,
fecha de descarga) para soportar dedupe y re-descarga incremental.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


_log = logging.getLogger(__name__)

_USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


@dataclass
class ResultadoDescarga:
    url: str
    estado: str          # "ok" / "404" / "403" / "timeout" / "error"
    archivo: Optional[Path] = None
    sha256: Optional[str] = None
    bytes: int = 0
    content_type: Optional[str] = None
    mensaje: str = ""


def _cliente_curl_cffi():
    try:
        from curl_cffi import requests as cffi_req
        return cffi_req
    except ImportError:
        return None


def _cliente_requests():
    try:
        import requests
        return requests
    except ImportError:
        return None


def descargar_bhn_pdf(url: str, destino: Path,
                        timeout: float = 45.0,
                        reintentos: int = 2,
                        cookies: Optional[dict] = None) -> ResultadoDescarga:
    """Descarga un PDF del portal SENAMHI con manejo de Cloudflare + retry.

    Devuelve ResultadoDescarga con estado y metadatos. No lanza excepciones:
    cualquier falla queda registrada en `estado` / `mensaje` para que el
    batch pueda continuar.
    """
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    res = ResultadoDescarga(url=url, estado="error")

    cffi = _cliente_curl_cffi()
    req = _cliente_requests()
    headers = {"User-Agent": _USER_AGENT,
                "Accept": "application/pdf,*/*;q=0.8",
                "Accept-Language": "es-BO,es;q=0.9,en;q=0.5",
                "Referer": "https://senamhi.gob.bo/index.php/rhidrologico"}

    for intento in range(reintentos + 1):
        try:
            if cffi is not None:
                # impersonate="chrome124" sortea Cloudflare TLS fingerprinting
                r = cffi.get(url, headers=headers, cookies=cookies or {},
                              timeout=timeout, impersonate="chrome124",
                              allow_redirects=True)
            elif req is not None:
                r = req.get(url, headers=headers, cookies=cookies or {},
                              timeout=timeout, allow_redirects=True)
            else:
                # urllib fallback
                from urllib.request import Request, urlopen
                rq = Request(url, headers=headers)
                with urlopen(rq, timeout=timeout) as resp:
                    body = resp.read()
                    code = resp.status
                    ctype = resp.headers.get("Content-Type", "")
                    class _R:
                        status_code = code
                        content = body
                        headers_ = {"Content-Type": ctype}
                        @property
                        def headers(self):
                            return self.headers_
                    r = _R()
        except Exception as e:  # noqa: BLE001
            res.mensaje = f"{type(e).__name__}: {str(e)[:80]}"
            res.estado = "timeout" if "timeout" in str(e).lower() else "error"
            if intento < reintentos:
                time.sleep(1.5 * (intento + 1))
                continue
            return res

        code = getattr(r, "status_code", 0)
        ctype = (r.headers.get("Content-Type", "") if hasattr(r, "headers")
                  else "")
        if code == 200:
            data = r.content
            if not data.startswith(b"%PDF"):
                # Cloudflare challenge HTML — falla suave
                res.estado = "cloudflare"
                res.mensaje = "Cloudflare HTML challenge (no PDF body)"
                return res
            destino.write_bytes(data)
            res.estado = "ok"
            res.archivo = destino
            res.sha256 = hashlib.sha256(data).hexdigest()
            res.bytes = len(data)
            res.content_type = ctype
            return res
        if code == 404:
            res.estado = "404"
            res.mensaje = "Boletín no publicado para esa fecha"
            return res
        if code == 403:
            res.estado = "403"
            res.mensaje = "Cloudflare 403 Forbidden — revisar User-Agent / IP"
            if intento < reintentos:
                time.sleep(2.0 * (intento + 1))
                continue
            return res
        res.estado = f"http_{code}"
        res.mensaje = f"HTTP {code}"
        if intento < reintentos:
            time.sleep(1.5 * (intento + 1))
            continue
        return res
    return res


# ─────────────────── Manifiesto local (caché incremental) ───────────────────

@dataclass
class Manifiesto:
    """Índice de archivos descargados con sha256 → fechas para dedupe."""
    archivos: dict = field(default_factory=dict)
    # ej. archivos[sha256] = {"path": "...", "url": "...", "fecha_descarga": "...",
    #                          "bytes": N, "fecha_boletin": "YYYY-MM-DD"}

    @classmethod
    def cargar(cls, path: Path) -> "Manifiesto":
        path = Path(path)
        if not path.exists():
            return cls()
        try:
            return cls(archivos=json.loads(path.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            return cls()

    def guardar(self, path: Path) -> None:
        Path(path).write_text(json.dumps(self.archivos, ensure_ascii=False,
                                            indent=2), encoding="utf-8")

    def conoce_sha(self, sha: str) -> bool:
        return sha in self.archivos

    def registrar(self, res: ResultadoDescarga,
                    fecha_boletin: str | None = None) -> None:
        import datetime as _dt
        if res.estado != "ok" or not res.sha256:
            return
        self.archivos[res.sha256] = {
            "url": res.url,
            "path": str(res.archivo),
            "bytes": res.bytes,
            "fecha_descarga": _dt.datetime.utcnow().isoformat() + "Z",
            "fecha_boletin": fecha_boletin,
        }
