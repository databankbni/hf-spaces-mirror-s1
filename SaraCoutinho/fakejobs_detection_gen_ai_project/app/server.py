import json
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from app.database import create_analysis, create_report, dashboard, get_analysis, init_db, list_analyses, list_reports, recent_flagged_cases
from app.extractor import build_job_payload
from app.scoring import evaluate_job
from agents.risk_agent import MODEL, MODEL_OPTIONS, analyze_with_ai


ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "static"

# Guardrail de entrada: um texto de vaga colado manualmente não passa disto.
# Protege custo (tokens enviados ao Ollama), memória e reduz a superfície
# disponível para esconder um payload de prompt injection longe do início do texto.
MAX_BODY_BYTES = 20_000


class PayloadTooLargeError(ValueError):
    """Levantado quando o corpo da requisição excede o limite aceito."""


class VagaCheckHandler(SimpleHTTPRequestHandler):
    server_version = "VagaCheck/1.0"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            self.json_response(
                {
                    "status": "ok",
                    "service": "VagaCheck",
                    "ia": {"provider": "Ollama", "model": MODEL, "options": MODEL_OPTIONS},
                }
            )
            return
        if path == "/api/analises":
            self.json_response({"items": list_analyses()})
            return
        if path.startswith("/api/analises/"):
            analysis_id = path.rsplit("/", 1)[-1]
            try:
                self.json_response(get_analysis(analysis_id))
            except KeyError:
                self.json_response({"erro": "Analise nao encontrada"}, HTTPStatus.NOT_FOUND)
            return
        if path == "/api/denuncias":
            self.json_response({"items": list_reports()})
            return
        if path == "/api/dashboard":
            self.json_response(dashboard())
            return
        if path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/analisar":
            try:
                data = self.read_json()
                if not str(data.get("texto_bruto", "")).strip():
                    self.json_response({"erro": "texto_bruto é obrigatório"}, HTTPStatus.BAD_REQUEST)
                    return
                job = build_job_payload(data)
                result = evaluate_job(job, historico_golpes=recent_flagged_cases())
                result["analise_ia"] = analyze_with_ai(job, result)
                persisted = create_analysis(job, result)
                self.json_response(persisted, HTTPStatus.CREATED)
            except PayloadTooLargeError as exc:
                self.json_response({"erro": str(exc)}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                self.json_response({"erro": f"Entrada inválida: {exc}"}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/denuncias":
            data = self.read_json()
            if not data.get("vaga_id") or not data.get("motivo"):
                self.json_response({"erro": "vaga_id e motivo sao obrigatorios"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                self.json_response(create_report(data["vaga_id"], data["motivo"]), HTTPStatus.CREATED)
            except Exception as exc:
                self.json_response({"erro": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self.json_response({"erro": "Rota nao encontrada"}, HTTPStatus.NOT_FOUND)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_BODY_BYTES:
            raise PayloadTooLargeError(
                f"Corpo da requisição excede o limite de {MAX_BODY_BYTES} bytes."
            )
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        return json.loads(raw or "{}")

    def json_response(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    init_db()
    server = ThreadingHTTPServer((host, port), VagaCheckHandler)
    print(f"VagaCheck rodando em http://{host}:{port}")
    server.serve_forever()
