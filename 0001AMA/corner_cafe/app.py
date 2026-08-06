"""Serve the static site; media under /sushi_atelier_artifacts/ from disk or HF Dataset via proxy.

Outgoing enquiry mail: POST /api/contact → SMTP → MAIL_TO (default pd3rvr@icloud.com).
Configure Space / process secrets: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, MAIL_TO,
optional SMTP_FROM. iCloud: SMTP_HOST=smtp.mail.me.com SMTP_PORT=587 + app-specific password.
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urljoin, urlparse

import aiosmtplib
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

BASE = Path(__file__).resolve().parent
ARTIFACTS_DIR = BASE / "sushi_atelier_artifacts"

MAIL_TO = os.environ.get("MAIL_TO", "pd3rvr@icloud.com").strip()
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.mail.me.com").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "").strip()
SMTP_FROM = os.environ.get("SMTP_FROM", "").strip() or SMTP_USER or MAIL_TO

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_CONTACT_HITS: dict[str, list[float]] = defaultdict(list)
_CONTACT_WINDOW_S = 600.0
_CONTACT_MAX = 8

# Dataset id on the Hub (no leading slash).
HF_DATASET = os.environ.get("SUSHI_ARTIFACTS_DATASET", "PIANDT/sushi_atelier_artifacts")
HF_REVISION = os.environ.get("SUSHI_ARTIFACTS_REVISION", "main")

RESOLVE_PREFIX = f"https://huggingface.co/datasets/{HF_DATASET}/resolve/{HF_REVISION}/"

_PASS_HEADERS = frozenset(
    {
        "content-type",
        "content-length",
        "content-range",
        "accept-ranges",
        "etag",
        "cache-control",
        "last-modified",
    }
)

_REDIRECT_STATUS = frozenset({301, 302, 303, 307, 308})
_MAX_REDIRECTS = 25

logger = logging.getLogger("uvicorn.error")


def resolve_hf_token() -> str | None:
    """Hub Bearer token for private datasets. Docker Spaces do not inject this unless you add it."""
    for key in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGING_FACE_TOKEN"):
        raw = os.environ.get(key)
        if raw and str(raw).strip():
            return str(raw).strip()

    path_env = os.environ.get("HF_TOKEN_PATH")
    if path_env:
        try:
            p = Path(path_env)
            if p.is_file():
                t = p.read_text(encoding="utf-8").strip()
                if t:
                    return t
        except OSError:
            pass

    for secret in (
        Path("/run/secrets/HF_TOKEN"),
        Path("/run/secrets/HUGGING_FACE_HUB_TOKEN"),
    ):
        try:
            if secret.is_file():
                t = secret.read_text(encoding="utf-8").strip()
                if t:
                    return t
        except OSError:
            pass

    try:
        from huggingface_hub.utils import get_token

        t = get_token()
        if t:
            return str(t).strip()
    except Exception:
        pass

    return None


def _strip_auth_if_cross_origin(prev_url: str, next_url: str, headers: dict[str, str]) -> None:
    """HF often 302s to a CDN; Bearer must not be sent cross-origin (httpx drops it anyway). Signed Location works without it."""
    if urlparse(prev_url).netloc != urlparse(next_url).netloc:
        headers.pop("Authorization", None)


async def _follow_resolve_head(
    url: str,
    headers: dict[str, str],
    timeout: httpx.Timeout,
) -> httpx.Response:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        current = url
        h = dict(headers)
        for _ in range(_MAX_REDIRECTS):
            r = await client.head(current, headers=h)
            if r.status_code in _REDIRECT_STATUS:
                loc = r.headers.get("location")
                if not loc:
                    raise HTTPException(status_code=502, detail="Upstream HEAD redirect without Location")
                nxt = urljoin(current, loc)
                _strip_auth_if_cross_origin(current, nxt, h)
                current = nxt
                continue
            return r
        raise HTTPException(status_code=502, detail="Too many upstream redirects")


async def _follow_resolve_get_stream(
    url: str,
    headers: dict[str, str],
    timeout: httpx.Timeout,
) -> tuple[httpx.Response, httpx.AsyncClient]:
    """
    Follow redirects without httpx's automatic follow_redirects=True (that strips Authorization on CDN hops).
    Caller must aclose() stream_resp and client after the body is consumed.
    """
    client = httpx.AsyncClient(timeout=timeout, follow_redirects=False)
    current = url
    h = dict(headers)
    try:
        for _ in range(_MAX_REDIRECTS):
            req = client.build_request("GET", current, headers=h)
            resp = await client.send(req, stream=True)
            if resp.status_code in _REDIRECT_STATUS:
                loc = resp.headers.get("location")
                await resp.aclose()
                if not loc:
                    raise HTTPException(status_code=502, detail="Upstream GET redirect without Location")
                nxt = urljoin(current, loc)
                _strip_auth_if_cross_origin(current, nxt, h)
                current = nxt
                continue
            return resp, client
        await client.aclose()
        raise HTTPException(status_code=502, detail="Too many upstream redirects")
    except HTTPException:
        await client.aclose()
        raise
    except Exception:
        await client.aclose()
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    if resolve_hf_token():
        logger.info(
            "sushi_atelier: artifact proxy token OK — private dataset %s should be readable.",
            HF_DATASET,
        )
    else:
        logger.warning(
            "sushi_atelier: no HF token (set Space secret HF_TOKEN with Read on datasets/%s). "
            "Proxy requests to private files will return 401.",
            HF_DATASET,
        )
    yield


app = FastAPI(lifespan=lifespan)


class ContactIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    subject: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=5000)
    website: str = ""  # honeypot — leave empty

    @field_validator("email")
    @classmethod
    def _email_ok(cls, v: str) -> str:
        email = (v or "").strip()
        if not _EMAIL_RE.match(email):
            raise ValueError("Invalid email address")
        return email

    @field_validator("subject", "message")
    @classmethod
    def _trim(cls, v: str) -> str:
        return (v or "").strip()


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for") or ""
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    if request.client:
        return request.client.host or "unknown"
    return "unknown"


def _rate_limited(ip: str) -> bool:
    now = time.monotonic()
    bucket = [t for t in _CONTACT_HITS[ip] if now - t < _CONTACT_WINDOW_S]
    _CONTACT_HITS[ip] = bucket
    if len(bucket) >= _CONTACT_MAX:
        return True
    bucket.append(now)
    _CONTACT_HITS[ip] = bucket
    return False


@app.get("/api/health")
async def api_health() -> dict[str, str | bool]:
    return {
        "ok": True,
        "mail_configured": bool(SMTP_USER and SMTP_PASSWORD),
        "mail_to": MAIL_TO,
    }


@app.post("/api/contact")
async def api_contact(payload: ContactIn, request: Request) -> JSONResponse:
    """Accept enquiry form fields and send via SMTP (no device mail client)."""
    if payload.website:
        # Silent success for bots that fill the honeypot.
        return JSONResponse({"ok": True})

    if _rate_limited(_client_ip(request)):
        raise HTTPException(status_code=429, detail="Too many messages. Please try again later.")

    if not SMTP_USER or not SMTP_PASSWORD:
        raise HTTPException(
            status_code=503,
            detail="Mail server is not configured (set SMTP_USER and SMTP_PASSWORD secrets).",
        )

    msg = EmailMessage()
    msg["Subject"] = f"[Corner cafe] {payload.subject}"
    msg["From"] = SMTP_FROM
    msg["To"] = MAIL_TO
    msg["Reply-To"] = payload.email
    msg.set_content(
        "Corner cafe website enquiry\n"
        f"From: {payload.email}\n"
        f"Subject: {payload.subject}\n\n"
        f"{payload.message}\n"
    )

    try:
        await aiosmtplib.send(
            msg,
            hostname=SMTP_HOST,
            port=SMTP_PORT,
            username=SMTP_USER,
            password=SMTP_PASSWORD,
            start_tls=True,
        )
    except aiosmtplib.errors.SMTPException as exc:
        logger.exception("SMTP send failed")
        raise HTTPException(status_code=502, detail=f"Mail server error: {exc}") from exc
    except OSError as exc:
        logger.exception("SMTP connection failed")
        raise HTTPException(status_code=502, detail=f"Mail server unreachable: {exc}") from exc

    return JSONResponse({"ok": True})


def _safe_artifact_path(rel: str) -> Path | None:
    if not rel or rel.startswith("/") or ".." in rel.split("/"):
        return None
    root = ARTIFACTS_DIR.resolve()
    p = (root / rel).resolve()
    try:
        p.relative_to(root)
    except ValueError:
        return None
    return p


def _upstream_headers(resp: httpx.Response) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in resp.headers.items():
        if k.lower() in _PASS_HEADERS:
            out[k] = v
    return out


@app.api_route("/sushi_atelier_artifacts/{path:path}", methods=["GET", "HEAD"])
async def sushi_artifacts(path: str, request: Request) -> Response:
    """Prefer ./sushi_atelier_artifacts files; else proxy the HF Dataset (Bearer token for private)."""
    rel = path.strip("/")
    if not rel:
        raise HTTPException(status_code=404, detail="Not found")

    local = _safe_artifact_path(rel)
    if local and local.is_file():
        return FileResponse(local)

    token = resolve_hf_token()
    url = RESOLVE_PREFIX + rel.replace("\\", "/")
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    rng = request.headers.get("range")
    if rng:
        headers["Range"] = rng
    if_range = request.headers.get("if-range")
    if if_range:
        headers["If-Range"] = if_range

    timeout = httpx.Timeout(120.0, connect=30.0)

    if request.method == "HEAD":
        try:
            r = await _follow_resolve_head(url, headers, timeout)
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e

        if r.status_code >= 400:
            hint = ""
            if r.status_code == 401:
                hint = (
                    " Space Settings → Repository secrets → add HF_TOKEN (read access to this dataset). "
                    "Docker Spaces do not auto-provide it."
                )
            raise HTTPException(
                status_code=r.status_code,
                detail=(r.text or "upstream error")[:800] + hint,
            )
        return Response(status_code=r.status_code, headers=_upstream_headers(r))

    try:
        stream_resp, client = await _follow_resolve_get_stream(url, headers, timeout)
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    if stream_resp.status_code >= 400:
        body = await stream_resp.aread()
        await stream_resp.aclose()
        await client.aclose()
        hint = ""
        if stream_resp.status_code == 401:
            hint = (
                " Add Space secret HF_TOKEN with Read on datasets/"
                + HF_DATASET
                + ". Docker Spaces require this for private datasets."
            )
        raise HTTPException(
            status_code=stream_resp.status_code,
            detail=(body.decode(errors="replace") or "upstream error")[:800] + hint,
        )

    code = stream_resp.status_code
    hdrs = _upstream_headers(stream_resp)

    async def stream_body():
        try:
            async for chunk in stream_resp.aiter_bytes():
                yield chunk
        finally:
            await stream_resp.aclose()
            await client.aclose()

    return StreamingResponse(stream_body(), status_code=code, headers=hdrs)


app.mount("/", StaticFiles(directory=str(BASE), html=True), name="site")
