from __future__ import annotations

from typing import Any, Callable

from app.scoring import evaluate_job


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "calcular_risco_vaga",
            "description": (
                "Calcula score, veredito e evidências por regras auditáveis. "
                "Deve ser chamada exatamente uma vez e seu veredito não pode ser alterado pelo modelo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "vaga": {
                        "type": "object",
                        "description": "Campos da vaga exatamente como recebidos da aplicação.",
                        "properties": {
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "company_profile": {"type": "string"},
                            "salary_range": {"type": "string"},
                            "required_education": {"type": "string"},
                            "required_experience": {"type": "string"},
                            "function": {"type": "string"},
                            "canal_contato": {"type": "string"},
                            "has_company_logo": {"type": "boolean"},
                            "has_questions": {"type": "boolean"},
                            "texto_bruto": {"type": "string"},
                        },
                        "required": ["title", "description"],
                    }
                },
                "required": ["vaga"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_casos_locais",
            "description": (
                "Busca no histórico local análises com texto ou título semelhante. "
                "Serve apenas como contexto; não confirma que a vaga atual é fraude."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "termo": {
                        "type": "string",
                        "description": "Termo curto e observável da vaga, como cargo ou domínio de contato.",
                        "minLength": 3,
                        "maxLength": 80,
                    },
                    "limite": {
                        "type": "integer",
                        "description": "Quantidade máxima de casos retornados.",
                        "minimum": 1,
                        "maximum": 5,
                        "default": 3,
                    },
                },
                "required": ["termo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sugerir_vagas_reais",
            "description": (
                "Sugere vagas legítimas parecidas (do histórico local marcado como provavel_legitima) "
                "e links de busca em plataformas confiáveis. Só deve ser chamada quando o veredito "
                "NÃO for prosseguir_com_cautela — não faz sentido oferecer alternativa a uma vaga já ok."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "area": {
                        "type": "string",
                        "description": "Cargo ou função da vaga analisada, ex: 'Analista de Dados'.",
                        "minLength": 3,
                        "maxLength": 80,
                    },
                    "localizacao": {
                        "type": "string",
                        "description": "Cidade ou 'Remoto', se conhecido.",
                        "maxLength": 60,
                    },
                },
                "required": ["area"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analisar_tendencias_area",
            "description": (
                "Retorna indicadores agregados por área (volume analisado e taxa de risco no "
                "histórico local), classificados em um quadrante simples. Não é dado de mercado "
                "em tempo real, é só o histórico desta instância. Chame no máximo uma vez."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "area": {
                        "type": "string",
                        "description": "Cargo, função ou departamento a analisar.",
                        "minLength": 3,
                        "maxLength": 80,
                    }
                },
                "required": ["area"],
            },
        },
    },
]

TRUSTED_SEARCH_TEMPLATES = {
    "linkedin": "https://www.linkedin.com/jobs/search/?keywords={area}&location={local}",
    "gov_emprega_brasil": "https://empregabrasil.mte.gov.br/",
    "catho": "https://www.catho.com.br/vagas/{area}/",
}


class ToolExecutionError(ValueError):
    pass


def _calculate(arguments: dict[str, Any]) -> dict[str, Any]:
    job = arguments.get("vaga")
    if not isinstance(job, dict):
        raise ToolExecutionError("O parâmetro 'vaga' deve ser um objeto.")
    return evaluate_job(job)


def _search(arguments: dict[str, Any]) -> dict[str, Any]:
    term = str(arguments.get("termo", "")).strip()
    if len(term) < 3:
        raise ToolExecutionError("O termo deve ter pelo menos 3 caracteres.")
    try:
        limit = max(1, min(5, int(arguments.get("limite", 3))))
    except (TypeError, ValueError) as exc:
        raise ToolExecutionError("O limite deve ser um número inteiro.") from exc

    from app.database import search_local_cases

    return {
        "aviso": "Histórico local é contexto, não confirmação de fraude.",
        "casos": search_local_cases(term[:80], limit),
    }


def _quote(value: str) -> str:
    from urllib.parse import quote_plus

    return quote_plus(value.strip())


def _suggest_real_jobs(arguments: dict[str, Any]) -> dict[str, Any]:
    area = str(arguments.get("area", "")).strip()
    if len(area) < 3:
        raise ToolExecutionError("O parâmetro 'area' deve ter pelo menos 3 caracteres.")
    local = str(arguments.get("localizacao", "") or "Brasil").strip()

    from app.database import similar_legit_jobs

    matches = similar_legit_jobs(area[:80], limit=3)
    links = {
        "linkedin": TRUSTED_SEARCH_TEMPLATES["linkedin"].format(area=_quote(area), local=_quote(local)),
        "catho": TRUSTED_SEARCH_TEMPLATES["catho"].format(area=_quote(area)),
        "gov_emprega_brasil": TRUSTED_SEARCH_TEMPLATES["gov_emprega_brasil"],
    }
    return {
        "aviso": "Vagas do histórico local não são garantia de vaga aberta agora; confirme antes de aplicar.",
        "vagas_similares_no_historico": matches,
        "links_busca_plataformas_confiaveis": links,
    }


def _area_trends(arguments: dict[str, Any]) -> dict[str, Any]:
    area = str(arguments.get("area", "")).strip()
    if len(area) < 3:
        raise ToolExecutionError("O parâmetro 'area' deve ter pelo menos 3 caracteres.")

    from app.database import trend_by_area

    return trend_by_area(area[:80])


TOOL_HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "calcular_risco_vaga": _calculate,
    "consultar_casos_locais": _search,
    "sugerir_vagas_reais": _suggest_real_jobs,
    "analisar_tendencias_area": _area_trends,
}


def execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        raise ToolExecutionError(f"Ferramenta desconhecida: {name}")
    try:
        return handler(arguments)
    except ToolExecutionError:
        raise
    except Exception as exc:
        raise ToolExecutionError(f"Falha ao executar {name}: {exc}") from exc
