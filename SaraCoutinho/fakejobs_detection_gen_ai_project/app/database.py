import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


DB_PATH = Path("data/vagacheck.db")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return str(uuid.uuid4())


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db() -> None:
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS usuarios (
                id TEXT PRIMARY KEY,
                nome TEXT NOT NULL,
                email TEXT NOT NULL,
                criado_em TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS vagas (
                id TEXT PRIMARY KEY,
                texto_bruto TEXT,
                fonte TEXT NOT NULL,
                title TEXT,
                location TEXT,
                department TEXT,
                salary_range TEXT,
                company_profile TEXT,
                description TEXT,
                requirements TEXT,
                benefits TEXT,
                telecommuting INTEGER NOT NULL DEFAULT 0,
                has_company_logo INTEGER NOT NULL DEFAULT 0,
                has_questions INTEGER NOT NULL DEFAULT 0,
                employment_type TEXT,
                required_experience TEXT,
                required_education TEXT,
                industry TEXT,
                function TEXT,
                canal_contato TEXT,
                criado_em TEXT NOT NULL,
                usuario_id TEXT NOT NULL,
                FOREIGN KEY(usuario_id) REFERENCES usuarios(id)
            );

            CREATE TABLE IF NOT EXISTS analises (
                id TEXT PRIMARY KEY,
                vaga_id TEXT NOT NULL UNIQUE,
                score_risco INTEGER NOT NULL,
                veredito TEXT NOT NULL,
                confianca TEXT NOT NULL,
                analise_ia_json TEXT,
                criado_em TEXT NOT NULL,
                FOREIGN KEY(vaga_id) REFERENCES vagas(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS red_flags (
                id TEXT PRIMARY KEY,
                analise_id TEXT NOT NULL,
                codigo TEXT NOT NULL,
                descricao TEXT NOT NULL,
                peso INTEGER NOT NULL,
                trecho_evidencia TEXT,
                FOREIGN KEY(analise_id) REFERENCES analises(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS denuncias (
                id TEXT PRIMARY KEY,
                vaga_id TEXT NOT NULL,
                usuario_id TEXT NOT NULL,
                motivo TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pendente',
                criado_em TEXT NOT NULL,
                FOREIGN KEY(vaga_id) REFERENCES vagas(id) ON DELETE CASCADE,
                FOREIGN KEY(usuario_id) REFERENCES usuarios(id)
            );

            CREATE INDEX IF NOT EXISTS idx_vagas_usuario ON vagas(usuario_id);
            CREATE INDEX IF NOT EXISTS idx_analises_vaga ON analises(vaga_id);
            CREATE INDEX IF NOT EXISTS idx_flags_analise ON red_flags(analise_id);
            """
        )
        columns = {row[1] for row in db.execute("PRAGMA table_info(analises)").fetchall()}
        if "analise_ia_json" not in columns:
            db.execute("ALTER TABLE analises ADD COLUMN analise_ia_json TEXT")
        db.execute(
            """
            INSERT OR IGNORE INTO usuarios (id, nome, email, criado_em)
            VALUES ('usuario-demo', 'Usuario demo', 'demo@vagacheck.local', ?)
            """,
            (now_iso(),),
        )


def create_analysis(job: dict, result: dict) -> dict:
    init_db()
    created = now_iso()
    vaga_id = new_id()
    analise_id = new_id()
    with connect() as db:
        db.execute(
            """
            INSERT INTO vagas (
                id, texto_bruto, fonte, title, location, department, salary_range,
                company_profile, description, requirements, benefits, telecommuting,
                has_company_logo, has_questions, employment_type, required_experience,
                required_education, industry, function, canal_contato, criado_em, usuario_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                vaga_id,
                job.get("texto_bruto", ""),
                job.get("fonte", "outro") or "outro",
                job.get("title", ""),
                job.get("location", ""),
                job.get("department", ""),
                job.get("salary_range", ""),
                job.get("company_profile", ""),
                job.get("description", ""),
                job.get("requirements", ""),
                job.get("benefits", ""),
                int(bool(job.get("telecommuting"))),
                int(bool(job.get("has_company_logo"))),
                int(bool(job.get("has_questions"))),
                job.get("employment_type", ""),
                job.get("required_experience", ""),
                job.get("required_education", ""),
                job.get("industry", ""),
                job.get("function", ""),
                job.get("canal_contato", ""),
                created,
                "usuario-demo",
            ),
        )
        db.execute(
            """
            INSERT INTO analises (id, vaga_id, score_risco, veredito, confianca, analise_ia_json, criado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                analise_id,
                vaga_id,
                result["score_risco"],
                result["veredito"],
                result["confianca"],
                json.dumps(result.get("analise_ia"), ensure_ascii=False) if result.get("analise_ia") else None,
                created,
            ),
        )
        db.executemany(
            """
            INSERT INTO red_flags (id, analise_id, codigo, descricao, peso, trecho_evidencia)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (new_id(), analise_id, flag["codigo"], flag["descricao"], flag["peso"], flag.get("trecho_evidencia"))
                for flag in result["red_flags"]
            ],
        )
    return get_analysis(analise_id)


def rows(query: str, params: tuple = ()) -> list[dict]:
    init_db()
    with connect() as db:
        return [dict(row) for row in db.execute(query, params).fetchall()]


def get_analysis(analysis_id: str) -> dict:
    analysis = rows(
        """
        SELECT a.*, v.title, v.fonte, v.company_profile, v.description, v.salary_range,
               v.canal_contato, v.criado_em AS vaga_criado_em
        FROM analises a
        JOIN vagas v ON v.id = a.vaga_id
        WHERE a.id = ?
        """,
        (analysis_id,),
    )
    if not analysis:
        raise KeyError(analysis_id)
    item = analysis[0]
    raw_ai = item.pop("analise_ia_json", None)
    item["analise_ia"] = json.loads(raw_ai) if raw_ai else None
    item["red_flags"] = rows(
        "SELECT codigo, descricao, peso, trecho_evidencia FROM red_flags WHERE analise_id = ? ORDER BY peso DESC",
        (analysis_id,),
    )
    return item


def list_analyses() -> list[dict]:
    return rows(
        """
        SELECT a.id, a.vaga_id, a.score_risco, a.veredito, a.confianca, a.criado_em,
               v.title, v.fonte, v.salary_range, v.canal_contato
        FROM analises a
        JOIN vagas v ON v.id = a.vaga_id
        ORDER BY a.criado_em DESC
        """
    )


def search_local_cases(term: str, limit: int = 3) -> list[dict]:
    pattern = f"%{term}%"
    return rows(
        """
        SELECT v.title, v.fonte, a.score_risco, a.veredito, a.criado_em
        FROM analises a
        JOIN vagas v ON v.id = a.vaga_id
        WHERE v.title LIKE ? OR v.description LIKE ? OR v.canal_contato LIKE ?
        ORDER BY a.criado_em DESC
        LIMIT ?
        """,
        (pattern, pattern, pattern, max(1, min(5, int(limit)))),
    )


def recent_flagged_cases(limit: int = 50) -> list[dict]:
    """Casos já marcados como golpe, usados pelo scoring para detectar
    repostagens (mesmo texto reaplicado com pequenas variações)."""
    return rows(
        """
        SELECT v.title, v.description, a.criado_em
        FROM vagas v
        JOIN analises a ON a.vaga_id = v.id
        WHERE a.veredito = 'provavel_golpe'
        ORDER BY a.criado_em DESC
        LIMIT ?
        """,
        (max(1, min(200, int(limit))),),
    )


def similar_legit_jobs(area: str, limit: int = 3) -> list[dict]:
    """Retrieval local (RAG-lite, sem embeddings): busca vagas do histórico já
    marcadas como legítimas pelo motor de regras, filtrando por área/cargo."""
    pattern = f"%{area}%"
    return rows(
        """
        SELECT v.title, v.fonte, v.location, v.salary_range, v.canal_contato
        FROM vagas v
        JOIN analises a ON a.vaga_id = v.id
        WHERE a.veredito = 'provavel_legitima'
          AND (v.function LIKE ? OR v.title LIKE ? OR v.department LIKE ?)
        ORDER BY v.criado_em DESC
        LIMIT ?
        """,
        (pattern, pattern, pattern, max(1, min(5, int(limit)))),
    )


def trend_by_area(area: str) -> dict:
    """Agrega indicadores locais por área (volume analisado e taxa de risco)
    e classifica em um quadrante simples, tipo Gartner. Isto NÃO é dado de
    mercado real: é só o histórico desta instância do VagaCheck."""
    pattern = f"%{area}%"
    matched = rows(
        """
        SELECT a.veredito, a.score_risco
        FROM analises a JOIN vagas v ON v.id = a.vaga_id
        WHERE v.function LIKE ? OR v.department LIKE ?
        """,
        (pattern, pattern),
    )
    overall = rows("SELECT veredito, score_risco FROM analises")

    def _stats(items: list[dict]) -> dict:
        total = len(items)
        if not total:
            return {"total": 0, "taxa_risco": 0.0, "score_medio": 0.0}
        risky = sum(1 for i in items if i["veredito"] != "provavel_legitima")
        media = sum(i["score_risco"] for i in items) / total
        return {"total": total, "taxa_risco": round(risky / total, 2), "score_medio": round(media, 1)}

    area_stats = _stats(matched)
    overall_stats = _stats(overall)

    if area_stats["total"] == 0:
        quadrante = "dados_insuficientes"
    else:
        alto_volume = area_stats["total"] >= 3
        alta_risco = area_stats["taxa_risco"] >= 0.5
        if alto_volume and not alta_risco:
            quadrante = "area_consolidada"
        elif alto_volume and alta_risco:
            quadrante = "area_visada_por_golpes"
        elif not alto_volume and alta_risco:
            quadrante = "risco_pontual_poucos_dados"
        else:
            quadrante = "area_emergente_poucos_dados"

    return {
        "aviso": "Baseado apenas no histórico local desta instância, não é pesquisa de mercado real.",
        "area": area,
        "estatisticas_area": area_stats,
        "estatisticas_gerais": overall_stats,
        "quadrante": quadrante,
    }


def create_report(vaga_id: str, motivo: str) -> dict:
    init_db()
    report_id = new_id()
    created = now_iso()
    with connect() as db:
        db.execute(
            """
            INSERT INTO denuncias (id, vaga_id, usuario_id, motivo, status, criado_em)
            VALUES (?, ?, 'usuario-demo', ?, 'pendente', ?)
            """,
            (report_id, vaga_id, motivo.strip(), created),
        )
    return {"id": report_id, "vaga_id": vaga_id, "motivo": motivo.strip(), "status": "pendente", "criado_em": created}


def list_reports() -> list[dict]:
    return rows(
        """
        SELECT d.*, v.title, a.score_risco, a.veredito
        FROM denuncias d
        JOIN vagas v ON v.id = d.vaga_id
        LEFT JOIN analises a ON a.vaga_id = v.id
        ORDER BY d.criado_em DESC
        """
    )


def dashboard() -> dict:
    analyses = list_analyses()
    reports = list_reports()
    total = len(analyses)
    average = round(sum(item["score_risco"] for item in analyses) / total, 1) if total else 0
    verdicts = {"provavel_golpe": 0, "atencao": 0, "provavel_legitima": 0}
    for item in analyses:
        verdicts[item["veredito"]] = verdicts.get(item["veredito"], 0) + 1
    return {
        "total_analises": total,
        "score_medio": average,
        "denuncias": len(reports),
        "vereditos": verdicts,
        "recentes": analyses[:5],
    }
