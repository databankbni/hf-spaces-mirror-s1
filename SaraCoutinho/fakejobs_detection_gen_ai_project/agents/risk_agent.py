from __future__ import annotations

import json
import os
from http.client import HTTPConnection, HTTPSConnection, HTTPException
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from tools.job_tools import TOOL_DEFINITIONS, ToolExecutionError, execute_tool


ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = ROOT / "prompts" / "system_prompt.txt"
EXAMPLES_PATH = ROOT / "prompts" / "few_shot_examples.json"

MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:1.5b")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
TOOL_MODE = os.environ.get("LLM_TOOL_MODE", "orchestrated").lower()
MODEL_OPTIONS = {
    "temperature": float(os.environ.get("LLM_TEMPERATURE", "0.2")),
    "top_p": float(os.environ.get("LLM_TOP_P", "0.9")),
    "seed": int(os.environ.get("LLM_SEED", "42")),
    "num_predict": int(os.environ.get("LLM_NUM_PREDICT", "320")),
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "resumo": {"type": "string"},
        "recomendacao": {
            "type": "string",
            "enum": ["interromper_contato", "validar_empresa", "prosseguir_com_cautela"],
        },
        "pontos_para_verificar": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 4},
        "limitacoes": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "alerta_privacidade": {"type": "string"},
        "sugestoes_vagas_reais": {"type": "array"},
        "tendencia_area": {"type": "string"},
    },
    "required": ["resumo", "recomendacao", "pontos_para_verificar", "limitacoes", "alerta_privacidade"],
}


class ChatClient(Protocol):
    def chat(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class OllamaClient:
    def __init__(self, base_url: str = OLLAMA_URL, timeout: float | None = None):
        self.base_url = base_url
        self.timeout = timeout or float(os.environ.get("OLLAMA_TIMEOUT", "120"))

    def chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        parsed = urlsplit(self.base_url)
        connection_type = HTTPSConnection if parsed.scheme == "https" else HTTPConnection
        connection = connection_type(parsed.hostname, parsed.port, timeout=self.timeout)
        try:
            path = f"{parsed.path.rstrip('/')}/api/chat"
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            connection.request("POST", path, body=body, headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            raw = response.read().decode("utf-8")
            if response.status >= 400:
                raise RuntimeError(f"Ollama respondeu HTTP {response.status}: {raw[:200]}")
            return json.loads(raw)
        except (OSError, HTTPException, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Ollama indisponível ou retornou resposta inválida: {exc}") from exc
        finally:
            connection.close()


def _load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def _load_examples() -> list[dict[str, Any]]:
    return json.loads(EXAMPLES_PATH.read_text(encoding="utf-8"))


def _untrusted_job_block(job: dict[str, Any]) -> str:
    serialized = json.dumps(job, ensure_ascii=False, indent=2)
    serialized = serialized.replace("<", "\\u003c").replace(">", "\\u003e")
    return f"Analise os dados abaixo.\n<vaga_nao_confiavel>\n{serialized}\n</vaga_nao_confiavel>"


def _messages(job: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": _load_prompt()},
        {"role": "user", "content": _untrusted_job_block(job)},
    ]


def _example_guidance() -> str:
    examples = [
        {"resultado_da_tool": example["tool_result"], "saida_esperada": example["output"]}
        for example in _load_examples()
    ]
    return (
        "A tool obrigatória já respondeu. Gere agora somente o JSON final. "
        "Use estes exemplos contrastivos de tom e estrutura, sem copiar evidências que não pertençam ao caso atual:\n"
        + json.dumps(examples, ensure_ascii=False)
    )


def _parse_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("Argumentos da ferramenta não são um objeto JSON.")


def _validate_output(value: Any, expected_recommendation: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("A saída estruturada não é um objeto.")
    required = set(OUTPUT_SCHEMA["required"])
    if not required.issubset(value):
        raise ValueError("A saída estruturada não contém todos os campos obrigatórios.")
    if value["recomendacao"] != expected_recommendation:
        raise ValueError("A recomendação do modelo contradiz a ferramenta determinística.")
    if not isinstance(value["pontos_para_verificar"], list) or not 2 <= len(value["pontos_para_verificar"]) <= 4:
        raise ValueError("A quantidade de pontos para verificar é inválida.")
    if not isinstance(value["limitacoes"], list) or not value["limitacoes"]:
        raise ValueError("A saída deve declarar ao menos uma limitação.")

    output = {key: value[key] for key in OUTPUT_SCHEMA["required"]}
    if expected_recommendation != "prosseguir_com_cautela":
        sugestoes = value.get("sugestoes_vagas_reais")
        if not isinstance(sugestoes, list) or not sugestoes:
            raise ValueError(
                "Quando a recomendação não é prosseguir_com_cautela, "
                "sugestoes_vagas_reais é obrigatório e não pode ficar vazio."
            )
        output["sugestoes_vagas_reais"] = sugestoes[:3]
    if isinstance(value.get("tendencia_area"), str) and value["tendencia_area"].strip():
        output["tendencia_area"] = value["tendencia_area"].strip()
    return output


def _compact_tool_result(name: str, result: dict[str, Any]) -> dict[str, Any]:
    if name != "calcular_risco_vaga":
        return result
    return {
        "score_risco": result["score_risco"],
        "veredito": result["veredito"],
        "confianca": result["confianca"],
        "red_flags": [
            {
                "codigo": flag["codigo"],
                "descricao": flag["descricao"],
                "trecho_evidencia": flag.get("trecho_evidencia"),
            }
            for flag in result.get("red_flags", [])
        ],
    }


def _fallback(
    deterministic: dict[str, Any],
    reason: str,
    tools_used: list[str] | None = None,
    tool_call_mode: str | None = None,
) -> dict[str, Any]:
    verdict = deterministic["veredito"]
    recommendation = {
        "provavel_golpe": "interromper_contato",
        "atencao": "validar_empresa",
        "provavel_legitima": "prosseguir_com_cautela",
    }[verdict]
    flags = deterministic.get("red_flags", [])
    evidence = ", ".join(flag["descricao"].lower() for flag in flags[:3]) or "nenhum sinal forte nas regras locais"
    return {
        "status": "fallback_sem_ia",
        "modelo": MODEL,
        "resumo": f"O motor auditável encontrou {evidence}. A explicação generativa não foi usada nesta análise.",
        "recomendacao": recommendation,
        "pontos_para_verificar": [
            "Confirme a vaga no site oficial da empresa, sem usar links enviados pelo contato.",
            "Valide a identidade do recrutador por um canal corporativo independente.",
        ],
        "limitacoes": ["O modelo local não respondeu; resultado baseado somente nas regras determinísticas."],
        "alerta_privacidade": "Não envie pagamentos, senhas, dados bancários ou documentos antes de validar a empresa.",
        "ferramentas_usadas": tools_used or [],
        "modo_tool_call": tool_call_mode,
        "erro_tecnico": reason[:240],
    }


def _check_grounding(output: dict[str, Any], tool_results_by_name: dict[str, Any]) -> None:
    """Guardrail de saída: garante que o texto gerado não inventa links, vagas
    ou verificações que as tools nunca retornaram. Roda depois de _validate_output."""
    sugestoes = output.get("sugestoes_vagas_reais")
    if sugestoes:
        vagas_tool = tool_results_by_name.get("sugerir_vagas_reais", {})
        links_validos = set(vagas_tool.get("links_busca_plataformas_confiaveis", {}).values())
        titulos_validos = {
            item.get("title", "") for item in vagas_tool.get("vagas_similares_no_historico", [])
        }
        for sugestao in sugestoes:
            link = str(sugestao.get("link_ou_observacao", ""))
            titulo = str(sugestao.get("titulo", ""))
            if link.startswith("http") and link not in links_validos:
                raise ValueError(f"sugestoes_vagas_reais cita um link que a tool não retornou: {link}")
            if titulo and titulo not in titulos_validos and not vagas_tool:
                raise ValueError("sugestoes_vagas_reais foi preenchido sem que a tool sugerir_vagas_reais fosse chamada.")

    tendencia = str(output.get("tendencia_area", "")).strip()
    if tendencia:
        if "analisar_tendencias_area" not in tool_results_by_name:
            raise ValueError("tendencia_area foi preenchida sem que a tool analisar_tendencias_area fosse chamada.")
        if "dados internos" not in tendencia.lower():
            raise ValueError("tendencia_area deve identificar explicitamente que usa dados internos.")

    frases_proibidas = ("cnpj confirmado", "verificamos a empresa", "consultamos o registro")
    resumo = str(output.get("resumo", "")).lower()
    achada = next((frase for frase in frases_proibidas if frase in resumo), None)
    if achada:
        raise ValueError(f"resumo afirma verificação externa não realizada: '{achada}'")


def analyze_with_ai(
    job: dict[str, Any],
    deterministic: dict[str, Any],
    client: ChatClient | None = None,
    force_tool_preflight: bool | None = None,
) -> dict[str, Any]:
    client = client or OllamaClient()
    messages = _messages(job)
    tools_used: list[str] = []
    tool_results_by_name: dict[str, Any] = {}
    tool_verdict: str | None = None
    tool_call_mode = "modelo"
    correction_attempts = 0
    max_corrections = 1

    try:
        preflight = TOOL_MODE == "orchestrated" if force_tool_preflight is None else force_tool_preflight
        if preflight:
            result = execute_tool("calcular_risco_vaga", {"vaga": job})
            tool_verdict = result["veredito"]
            tools_used.append("calcular_risco_vaga")
            tool_results_by_name["calcular_risco_vaga"] = result
            tool_call_mode = "orquestrador"
            messages.extend(
                [
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {"function": {"name": "calcular_risco_vaga", "arguments": {"vaga": job}}}
                        ],
                    },
                    {
                        "role": "tool",
                        "tool_name": "calcular_risco_vaga",
                        "content": json.dumps(
                            _compact_tool_result("calcular_risco_vaga", result), ensure_ascii=False
                        ),
                    },
                    {"role": "user", "content": _example_guidance()},
                ]
            )

        for _ in range(3):
            payload = {
                "model": MODEL,
                "messages": messages,
                "stream": False,
                "options": MODEL_OPTIONS,
            }
            available_tools = [
                definition
                for definition in TOOL_DEFINITIONS
                if definition["function"]["name"] not in tools_used
            ]
            if deterministic["veredito"] == "provavel_legitima":
                available_tools = [
                    definition
                    for definition in available_tools
                    if definition["function"]["name"] != "sugerir_vagas_reais"
                ]
            if available_tools:
                payload["tools"] = available_tools
            if "calcular_risco_vaga" in tools_used:
                payload["format"] = "json"
            response = client.chat(payload)
            message = response.get("message", {})
            tool_calls = message.get("tool_calls") or []
            if tool_calls:
                messages.append(message)
                calculated_this_turn = False
                for call in tool_calls:
                    function = call.get("function", {})
                    name = function.get("name", "")
                    if name in tools_used:
                        raise ValueError(f"A ferramenta {name} foi chamada mais de uma vez.")
                    if name == "sugerir_vagas_reais" and deterministic["veredito"] == "provavel_legitima":
                        raise ValueError("sugerir_vagas_reais não deve ser chamada para uma vaga de baixo risco.")
                    arguments = _parse_arguments(function.get("arguments", {}))
                    if name == "calcular_risco_vaga":
                        arguments = {"vaga": job}
                    result = execute_tool(name, arguments)
                    tools_used.append(name)
                    tool_results_by_name[name] = result
                    if name == "calcular_risco_vaga":
                        tool_verdict = result["veredito"]
                        calculated_this_turn = True
                    messages.append(
                        {
                            "role": "tool",
                            "tool_name": name,
                            "content": json.dumps(_compact_tool_result(name, result), ensure_ascii=False),
                        }
                    )
                if calculated_this_turn:
                    messages.append({"role": "user", "content": _example_guidance()})
                continue

            if "calcular_risco_vaga" not in tools_used:
                # Modelos locais pequenos podem anunciar suporte a tools e ainda assim
                # responder diretamente. O orquestrador força a etapa crítica e envia
                # o resultado no papel `tool`; a decisão nunca fica a cargo do LLM.
                result = execute_tool("calcular_risco_vaga", {"vaga": job})
                tool_verdict = result["veredito"]
                tools_used.append("calcular_risco_vaga")
                tool_results_by_name["calcular_risco_vaga"] = result
                tool_call_mode = "orquestrador"
                messages.extend(
                    [
                        {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "calcular_risco_vaga",
                                        "arguments": {"vaga": job},
                                    }
                                }
                            ],
                        },
                        {
                            "role": "tool",
                            "tool_name": "calcular_risco_vaga",
                            "content": json.dumps(
                                _compact_tool_result("calcular_risco_vaga", result), ensure_ascii=False
                            ),
                        },
                        {"role": "user", "content": _example_guidance()},
                    ]
                )
                continue
            if tool_verdict != deterministic["veredito"]:
                raise ValueError("A ferramenta retornou um veredito inconsistente.")
            expected = {
                "provavel_golpe": "interromper_contato",
                "atencao": "validar_empresa",
                "provavel_legitima": "prosseguir_com_cautela",
            }[deterministic["veredito"]]

            # Agente de correção: erros de formato/schema não caem direto no
            # fallback determinístico. O modelo ganha uma chance de se corrigir,
            # apontando o erro exato, antes de esgotarmos o orçamento de ciclos.
            try:
                content = message.get("content", "")
                parsed = content if isinstance(content, dict) else json.loads(content)
                output = _validate_output(parsed, expected)
                _check_grounding(output, tool_results_by_name)
            except (ValueError, json.JSONDecodeError) as validation_error:
                if correction_attempts >= max_corrections:
                    raise
                correction_attempts += 1
                messages.append(message)
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Sua última resposta não passou na validação de formato. "
                            f"Erro específico: {validation_error}. "
                            "Corrija e responda APENAS com o JSON completo e válido, "
                            "seguindo exatamente o formato_de_saida definido."
                        ),
                    }
                )
                continue

            return {
                "status": "gerada_por_ia",
                "modelo": MODEL,
                **output,
                "ferramentas_usadas": tools_used,
                "modo_tool_call": tool_call_mode,
                "correcoes_aplicadas": correction_attempts,
            }
        raise ValueError("O agente excedeu o limite de três ciclos.")
    except (RuntimeError, ValueError, ToolExecutionError, json.JSONDecodeError) as exc:
        return _fallback(deterministic, str(exc), tools_used, tool_call_mode)
