"""FastAPI server for the HELITEB commercial agent.

Production-ready with:
    - CORS restricted to configured origins (Vercel frontend by default).
    - Defensive security headers (HSTS, X-Frame-Options, ...).
    - In-memory IP-based rate limiting (30 req/min, stdlib only).
    - Strict request validation (Pydantic v2 + custom validators).
    - Sanitised error responses that never leak server internals.
    - Enhanced /health endpoint with version + timestamp.
"""
from __future__ import annotations

import base64
import logging
import mimetypes
import os
import re
from datetime import datetime, timezone
from typing import Literal

import httpx
from fpdf import FPDF
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field, field_validator

from db.supabase import get_product_by_sap
from graph import agent_graph
from middleware import (
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    register_exception_handlers,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
APP_VERSION = "1.0.0"
AGENT_NAME = "HELITEB-Sales-v1"
MAX_MESSAGE_LENGTH = 2000
RATE_LIMIT_MAX_REQUESTS = 30
RATE_LIMIT_WINDOW_SECONDS = 60

WHATSAPP_VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "dev-token-change-me")


def _parse_allowed_origins() -> list[str]:
    """Read ``ALLOWED_ORIGINS`` from env (comma-separated).

    A value of ``"*"`` is honoured literally so operators can opt into a
    permissive CORS policy for development. The default list covers the
    Vercel-hosted frontend and local development.
    """
    raw = os.environ.get("ALLOWED_ORIGINS", "").strip()
    if raw:
        if raw == "*":
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]
    return [
        "https://*.hf.space",
        "https://heliteb.vercel.app",
        "https://heliteb-agente-ia.vercel.app",
        "https://www.heliteb.com",
        "https://heliteb.com",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


ALLOWED_ORIGINS: list[str] = _parse_allowed_origins()

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger("heliteb.main")


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
app = FastAPI(
    title="HELITEB AI Agent",
    version=APP_VERSION,
    # Do not expose docs in production by default. Set EXPOSE_DOCS=1 to enable.
    docs_url="/docs" if os.environ.get("EXPOSE_DOCS") == "1" else None,
    redoc_url=None,
    openapi_url="/openapi.json" if os.environ.get("EXPOSE_DOCS") == "1" else None,
)

# Starlette wraps middlewares in the order they are added: the FIRST
# ``add_middleware`` call is the INNERMOST wrapper (closest to the app),
# and the LAST call is the OUTERMOST wrapper (closest to the client).
# Request flow:  client -> SecurityHeaders -> RateLimit -> CORS -> app
# Response flow: app -> CORS -> RateLimit -> SecurityHeaders -> client
#
# This order ensures:
#   - CORS preflights are handled by the CORS middleware (innermost).
#   - OPTIONS preflights do NOT consume rate-limit budget
#     (RateLimitMiddleware explicitly skips OPTIONS).
#   - Security headers are applied to EVERY outgoing response, including
#     429s, 500s, and OPTIONS preflight replies.

# CORS (innermost): handles preflight + adds CORS headers to responses.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
    max_age=600,
)

# Rate limiting (middle): 30 req/min per IP, with /health and OPTIONS exempt.
app.add_middleware(
    RateLimitMiddleware,
    max_requests=RATE_LIMIT_MAX_REQUESTS,
    window_seconds=RATE_LIMIT_WINDOW_SECONDS,
    exempt_paths=("/health",),
)

# Security headers (outermost): applied last so they wrap the final response.
app.add_middleware(
    SecurityHeadersMiddleware,
    no_store_paths=("/agent/query",),
)

# User-friendly error responses.
register_exception_handlers(app)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
Channel = Literal["web", "whatsapp"]


class QueryRequest(BaseModel):
    """Incoming payload for the agent query endpoint."""

    message: str = Field(
        ...,
        min_length=1,
        max_length=MAX_MESSAGE_LENGTH,
        description=(
            f"User message, stripped of leading/trailing whitespace. "
            f"Max {MAX_MESSAGE_LENGTH} characters."
        ),
    )
    channel: Channel = Field(
        default="web",
        description="Originating channel. Must be 'web' or 'whatsapp'.",
    )
    session_id: str = Field(
        default="default",
        max_length=100,
        description="Session identifier for conversation memory. Defaults to 'default'.",
    )

    @field_validator("message")
    @classmethod
    def _sanitize_message(cls, value: str) -> str:
        """Strip whitespace and reject empty or whitespace-only messages."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("message must not be empty or whitespace-only")
        # Reject control characters that have no legitimate place in chat.
        if any(ord(ch) < 0x20 and ch not in "\n\t" for ch in stripped):
            raise ValueError("message contains invalid control characters")
        return stripped


class QueryResponse(BaseModel):
    response: str
    intent: str


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    agent: str
    timestamp: str


class QuotationRequest(BaseModel):
    """Incoming payload for the /agent/quotation/pdf endpoint."""

    codigos_sap: list[str] = Field(..., min_length=1, max_length=50)
    cliente_nombre: str = Field(..., min_length=1, max_length=200)
    cliente_whatsapp: str = Field(default="", max_length=20)
    notas: str = Field(default="", max_length=1000)
    consulta: str = Field(default="", max_length=500)  # user's original query


class EmailPdfRequest(BaseModel):
    """Payload for sending a quotation PDF via email."""

    to: str = Field(..., min_length=1, max_length=200, description="Recipient email address")
    codigos_sap: list[str] = Field(..., min_length=1, max_length=50)
    cliente_nombre: str = Field(..., min_length=1, max_length=200)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness probe. Returns version, agent name, and ISO-8601 timestamp."""
    return HealthResponse(
        status="ok",
        version=APP_VERSION,
        agent=AGENT_NAME,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# (MemorySaver handles conversation context — old cache removed)

@app.post("/agent/query", response_model=QueryResponse)
async def agent_query(req: QueryRequest) -> QueryResponse:
    """Main agent endpoint. Receives a user message and returns a reply.

    The request body is validated by ``QueryRequest`` (length, channel,
    whitespace) before this function is ever called, so by the time we
    run, ``req.message`` and ``req.channel`` are guaranteed safe.
    """
    try:
        msg = req.message

        # Use session_id from request for per-user conversation memory.
        # LangGraph's MemorySaver + add_messages reducer handles history
        # accumulation automatically — no manual history loading needed.
        config = {"configurable": {"thread_id": req.session_id}}

        state = {
            "messages": [{"role": "user", "content": msg}],
            "intent": "",
            "tool_result": "",
            "response": "",
            "email_address": "",
            # Memory fields (recent_saps, recent_linea, etc.) are NOT
            # passed here — LangGraph preserves them from the checkpoint.
        }

        result = agent_graph.invoke(state, config)

        # ── Cotización con envío automático por email ──────────────────
        email_addr = str(result.get("email_address", "") or "")
        quote_saps = str(result.get("quotation_saps", "") or "")
        if email_addr and quote_saps:
            try:
                sap_list = [s.strip() for s in quote_saps.split(",") if s.strip()]
                if sap_list:
                    quote_req = QuotationRequest(codigos_sap=sap_list, cliente_nombre="Helia", consulta=result.get("quotation_description", req.message))
                    pdf_bytes, filename, _ = _generate_quotation_pdf_bytes(quote_req)
                    await _send_email_pdf(to=email_addr, pdf_bytes=pdf_bytes, filename=filename, product_count=len(sap_list))
                    logger.info("quotation_email_sent to=%s saps=%s", email_addr, quote_saps)
            except Exception:
                logger.exception("quotation_email_failed to=%s", email_addr)
                result["response"] = (
                    "❌ No se pudo enviar la cotización por email. Verifica la dirección e intenta de nuevo."
                )

        # Guardar contexto para el siguiente turno


        return QueryResponse(
            response=result["response"],
            intent=result["intent"],
        )
    except HTTPException:
        # Re-raise explicit HTTP errors (e.g. raised by the graph layer).
        raise
    except Exception as exc:  # noqa: BLE001 - intentional broad catch
        # Log full traceback server-side; return a sanitised message to
        # the client. The global HTTPException handler will turn the
        # 5xx detail into a generic user-facing string.
        logger.exception(
            "agent_query_failed channel=%s message_len=%d",
            req.channel,
            len(req.message),
        )
        raise HTTPException(
            status_code=500,
            detail="An internal error occurred. Please try again shortly.",
        ) from exc


# ---------------------------------------------------------------------------
# Quotation PDF generator — produces a branded PDF quotation via fpdf2
# ---------------------------------------------------------------------------

# Branding colours
_BRAND_RED = (204, 0, 0)        # #CC0000
_BRAND_BLUE = (15, 72, 171)     # #0F48AB
_BRAND_BLACK = (0, 0, 0)        # #000000


def _format_cop(value: float) -> str:
    """Format a numeric value as Colombian pesos with dot-thousands separator."""
    # Format with comma as thousands separator, then swap to dots
    formatted = f"{value:,.0f}".replace(",", ".")
    return f"$ {formatted} COP"


def _generate_quotation_pdf_bytes(
    req: QuotationRequest,
) -> tuple[bytes, str, str]:
    """Generate a branded PDF quotation and return (pdf_bytes, filename, mime).

    Fetches product details from Supabase, builds a professional PDF with
    HELITEB branding (red title, blue section headers, product table,
    totals, terms & conditions).
    """
    # Fetch products from Supabase
    items: list[dict] = []
    total = 0.0
    for codigo in req.codigos_sap:
        p_resp = get_product_by_sap(codigo.strip())
        p = p_resp.data if p_resp and p_resp.data else None
        if p:
            precios = p.get("heliteb_precios") or []
            precio = (
                float(precios[0].get("precio_msrp_cop", 0)) if isinstance(precios, list) and precios
                else float(precios.get("precio_msrp_cop", 0)) if isinstance(precios, dict)
                else 0.0
            )
            modelo = f"{p.get('marca', '')} {p.get('modelo', '')}".strip()
            desc = (p.get("descripcion") or "").replace("\n", " ")
            # Remove non-latin-1 characters (Helvetica core font limitation)
            desc = desc.encode("latin-1", errors="replace").decode("latin-1")[:200]
            items.append(
                {
                    "codigo_sap": codigo.strip(),
                    "modelo": modelo,
                    "descripcion": desc,
                    "precio": precio,
                }
            )
            total += precio

    if not items:
        raise HTTPException(
            status_code=404,
            detail="No se encontraron productos con los códigos SAP proporcionados",
        )

    # Build quotation number
    cot_num = f"COT-{datetime.now().year}-{datetime.now().strftime('%m%d%H%M')}"

    # ── Build PDF with fpdf2 ──────────────────────────────────────────────
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=25)
    pdf.add_page()

    # --- Header: HELITEB SAS (red, centred, large) ---
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(*_BRAND_RED)
    pdf.cell(0, 12, "HELITEB SAS", new_x="LMARGIN", new_y="NEXT", align="C")

    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(*_BRAND_BLACK)
    pdf.cell(
        0, 7, "Soluciones en Seguridad Electrónica",
        new_x="LMARGIN", new_y="NEXT", align="C",
    )
    pdf.ln(6)

    # --- Quotation metadata ---
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*_BRAND_BLACK)
    pdf.cell(0, 6, f"Cotización: {cot_num}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Remitente: Helia - Asistente HELITEB", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(
        0, 6,
        f"Fecha: {datetime.now().strftime('%d de %B de %Y')}",
        new_x="LMARGIN", new_y="NEXT",
    )
    if req.cliente_whatsapp:
        pdf.cell(0, 6, f"WhatsApp: {req.cliente_whatsapp}", new_x="LMARGIN", new_y="NEXT")
    if req.consulta:
        pdf.set_font("Helvetica", "I", 10)
        pdf.set_text_color(*_BRAND_BLUE)
        pdf.cell(0, 6, f"Consulta: {req.consulta}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # --- Products table ---
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*_BRAND_BLUE)
    pdf.cell(0, 7, "Detalle de Productos", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    # Table header — SAP | Producto | Descripción | Precio
    col_w = [25, 42, 72, 38]
    headers = ["Código", "Producto", "Descripción", "Precio"]

    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(*_BRAND_BLUE)
    pdf.set_text_color(255, 255, 255)
    for w, h in zip(col_w, headers):
        pdf.cell(w, 7, h, border=1, fill=True, align="C")
    pdf.ln()

    # Table rows
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(*_BRAND_BLACK)
    pdf.set_fill_color(245, 245, 245)
    for i, item in enumerate(items):
        row_h = 6
        fill = i % 2 == 0
        pdf.cell(col_w[0], row_h, item["codigo_sap"], border=1, fill=fill, align="C")
        pdf.cell(col_w[1], row_h, item["modelo"][:28], border=1, fill=fill)
        pdf.cell(col_w[2], row_h, item["descripcion"][:55], border=1, fill=fill)
        pdf.cell(col_w[3], row_h, _format_cop(item["precio"]), border=1, fill=fill, align="R")
        pdf.ln()

    pdf.ln(4)

    # --- Notes ---
    if req.notas:
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_BRAND_BLACK)
        pdf.cell(0, 6, f"Notas: {req.notas}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

    # --- Terms & Conditions ---
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*_BRAND_BLUE)
    pdf.cell(0, 8, "Términos y Condiciones", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_BRAND_BLACK)
    terms = [
        "Precios en pesos colombianos (COP).",
        "Garantía oficial de 3 años en todos los productos.",
        "Soporte técnico especializado incluido.",
        "Factura electrónica disponible.",
        "Envío a toda Colombia.",
        "Validez de la cotización: 7 días hábiles.",
        "Precios sujetos a cambios sin previo aviso.",
    ]
    for t in terms:
        pdf.cell(0, 5, f"-  {t}", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(8)

    # --- Footer ---
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(*_BRAND_BLACK)
    pdf.cell(
        0, 6,
        "HELITEB SAS - Seguridad Electrónica Profesional",
        new_x="LMARGIN", new_y="NEXT", align="C",
    )

    pdf_bytes = pdf.output()
    filename = f"Cotizacion_HELITEB_{req.cliente_nombre.replace(' ', '_')}_{cot_num}.pdf"
    return pdf_bytes, filename, "application/pdf"


@app.post("/agent/quotation/pdf")
async def generate_quotation_pdf(req: QuotationRequest):
    """Generate a professional quotation PDF file.

    Fetches product details from Supabase, calculates totals,
    and returns a branded PDF document.
    """
    pdf_bytes, filename, media_type = _generate_quotation_pdf_bytes(req)
    return Response(
        content=pdf_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/agent/cotizacion")
async def generate_cotizacion(req: QuotationRequest):
    """Alias for /agent/quotation/pdf — returns the same branded PDF."""
    pdf_bytes, filename, media_type = _generate_quotation_pdf_bytes(req)
    return Response(
        content=pdf_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Audio STT — transcribe speech to text with Gemini 2.5 Flash
# ---------------------------------------------------------------------------
MAX_AUDIO_BYTES = 10 * 1024 * 1024  # 10 MB


@app.post("/agent/audio")
async def agent_audio_stt(
    audio: UploadFile = File(..., description="Audio file to transcribe"),
    language: str = Form(default="es-CO", description="Language code for transcription"),
):
    """Transcribe audio to text using Gemini 2.5 Flash Speech-To-Text.

    Does NOT invoke the agent graph — only transcription is performed.
    """
    # Validate file size — read the whole file into memory first
    audio_bytes = await audio.read()
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Audio file too large. Maximum size is {MAX_AUDIO_BYTES // (1024 * 1024)} MB.",
        )

    # Detect MIME type: prefer Content-Type from upload, fall back to filename guess
    mime_type = audio.content_type or mimetypes.guess_type(audio.filename or "audio.webm")[0]
    if not mime_type:
        mime_type = "audio/webm"

    # Base64-encode the audio bytes
    audio_b64 = base64.b64encode(audio_bytes).decode("ascii")

    # Build a multimodal HumanMessage with inline audio
    try:
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0.0,
            google_api_key=os.environ["GOOGLE_API_KEY"],
        )
        message = HumanMessage(
            content=[
                {
                    "type": "text",
                    "text": "Transcribe this audio to text in the requested language without commentary.",
                },
                {
                    "type": "audio",
                    "base64": audio_b64,
                    "mime_type": mime_type,
                },
            ]
        )
        result = llm.invoke([message])
        transcription = result.content.strip() if hasattr(result, "content") and result.content else ""

        return {"transcription": transcription, "success": True, "language": language}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("audio_stt_failed language=%s mime=%s", language, mime_type)
        raise HTTPException(
            status_code=500,
            detail="Audio transcription failed. Please try again.",
        ) from exc


# ── Email sender (Brevo API over HTTPS) ────────────────────────────────
async def _send_email_pdf(to: str, pdf_bytes: bytes, filename: str, product_count: int = 1) -> None:
    """Send a quotation PDF via Brevo API."""
    import base64 as _b64

    api_key = os.environ.get("BREVO_API_KEY", "")
    from_email = os.environ.get("FROM_EMAIL", "cotizaciones@heliteb.com")

    if not api_key:
        raise HTTPException(status_code=500, detail="BREVO_API_KEY not configured.")

    count_text = f"{product_count} producto{'s' if product_count != 1 else ''}"
    payload = {
        "sender": {"name": "Helia, asistente de Heliteb", "email": from_email},
        "to": [{"email": to}],
        "subject": f"Cotización HELITEB — {count_text}",
        "htmlContent": (
            f"<p>Hola,</p>"
            f"<p>Adjunto encontrarás la cotización solicitada con <strong>{count_text}</strong>.</p>"
            f"<p><em>— Helia, asistente comercial de HELITEB</em></p>"
            "<hr><p><small>HELITEB SAS — Seguridad Electrónica Profesional</small></p>"
        ),
        "attachment": [{
            "content": _b64.b64encode(pdf_bytes).decode(),
            "name": filename,
        }],
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={
                "api-key": api_key,
                "content-type": "application/json",
                "accept": "application/json",
            },
            json=payload,
        )
        if not resp.is_success:
            detail = resp.text[:500] if resp.text else "Brevo error"
            raise HTTPException(status_code=502, detail=detail)

    logger.info("email_sent to=%s filename=%s", to, filename)


# ── Endpoint: enviar PDF de cotización por email ──────────────────────
@app.post("/agent/email/send-pdf")
async def email_send_pdf(req: EmailPdfRequest):
    """Generate quotation PDF and send it via email."""
    quotation_req = QuotationRequest(codigos_sap=req.codigos_sap, cliente_nombre=req.cliente_nombre)
    pdf_bytes, filename, _ = _generate_quotation_pdf_bytes(quotation_req)
    await _send_email_pdf(to=req.to, pdf_bytes=pdf_bytes, filename=filename)
    return {"status": "sent", "to": req.to}
