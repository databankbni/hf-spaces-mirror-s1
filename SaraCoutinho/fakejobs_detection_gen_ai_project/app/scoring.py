import difflib
import re
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class RedFlagResult:
    codigo: str
    descricao: str
    peso: int
    trecho_evidencia: str | None = None


RED_FLAGS = {
    "SEM_LOGO_EMPRESA": ("Anuncio nao exibe logo da empresa", 20),
    "SEM_PERFIL_EMPRESA": ("Anuncio nao traz descricao da empresa", 20),
    "DESCRICAO_CURTA": ("Descricao da vaga muito curta para o cargo anunciado", 10),
    "SEM_PERGUNTAS_TRIAGEM": ("Processo nao inclui perguntas de triagem", 10),
    "SALARIO_INCOMPATIVEL": ("Faixa salarial irreal ou em formato estranho para o cargo", 20),
    "EDUCACAO_MINIMA_SALARIO_ALTO": ("Exige pouca qualificacao mas promete salario alto", 15),
    "TITULO_SUSPEITO": ("Titulo usa termos associados a golpes de vaga", 15),
    "COBRANCA_ANTECIPADA": ("Pedido de pagamento antes da contratacao", 30),
    "CANAL_GENERICO": ("Contato usa e-mail generico em vez de dominio proprio", 15),
    "URGENCIA_EXCESSIVA": ("Linguagem de urgencia para pressionar decisao rapida", 10),
    "TENTATIVA_MANIPULACAO_IA": ("Texto contem instrucao dirigida a um sistema de IA, tipico de tentativa de manipulacao", 25),
    "REPOSTAGEM_DE_GOLPE_CONHECIDO": ("Texto muito similar a uma vaga ja identificada como golpe no historico local", 30),
}

# Limiar de similaridade (0 a 1) acima do qual consideramos que a vaga nova é
# uma repostagem/variação de um golpe já identificado. Golpes costumam ser
# reaplicados com pequenas variações de texto, então essa checagem é mais forte
# que uma busca por palavra-chave: compara o texto inteiro, não só um termo.
REPOST_SIMILARITY_THRESHOLD = 0.72

# Um anúncio de vaga legítimo não tem motivo para se dirigir a um classificador
# de IA. Ver esse padrão no texto é, ao mesmo tempo, um guardrail de entrada
# (sinaliza tentativa de prompt injection) e um sinal de má-fé — por isso soma
# ao score em vez de só ser bloqueado silenciosamente.
PROMPT_INJECTION_KEYWORDS = (
    "ignore as instrucoes anteriores",
    "ignore as instruções anteriores",
    "ignore instrucoes anteriores",
    "ignore instruções anteriores",
    "desconsidere as instrucoes",
    "desconsidere as instruções",
    "esqueca suas regras",
    "esqueça suas regras",
    "you are now",
    "aja como",
    "system:",
    "nova instrucao:",
    "nova instrução:",
)

TITLE_KEYWORDS = (
    "data entry",
    "home based",
    "earn daily",
    "ganhe rapido",
    "renda extra",
    "trabalhe de casa",
)

PAYMENT_KEYWORDS = (
    "taxa",
    "pix",
    "boleto",
    "deposito",
    "depósito",
    "curso obrigatorio",
    "curso obrigatório",
    "uniforme",
    "exame admissional pago",
)

URGENCY_KEYWORDS = (
    "urgente",
    "responda agora",
    "tempo limitado",
    "ultimas vagas",
    "últimas vagas",
    "contratacao imediata",
    "contratação imediata",
)

LOW_EDUCATION = {"some high school", "high school", "unspecified", "ensino medio", "ensino médio"}
GENERIC_EMAIL_RE = re.compile(r"[\w.+-]+@(gmail|hotmail|outlook|yahoo|live)\.", re.I)


def _text(value: object) -> str:
    return str(value or "").strip()


def _contains_any(text: str, keywords: tuple[str, ...]) -> str | None:
    lowered = text.lower()
    for keyword in keywords:
        if keyword in lowered:
            return keyword
    return None


def _salary_numbers(salary_range: str) -> list[int]:
    return [int(match.replace(".", "")) for match in re.findall(r"\d[\d.]*", salary_range)]


def is_salary_suspicious(salary_range: str, required_experience: str = "", function: str = "") -> bool:
    salary_range = _text(salary_range)
    if not salary_range:
        return False

    numbers = _salary_numbers(salary_range)
    if not numbers:
        return True
    if len(numbers) >= 2 and min(numbers) > max(numbers):
        return True

    high = max(numbers)
    low = min(numbers)
    monthly_like = high <= 200_000
    if monthly_like and high >= 25_000:
        return True
    if not monthly_like and high >= 300_000:
        return True
    if low == 0 or high / max(low, 1) > 8:
        return True

    seniority = _text(required_experience).lower()
    area = _text(function).lower()
    juniorish = any(term in seniority for term in ("internship", "entry", "not applicable", "estagio"))
    operational = any(term in area for term in ("administrative", "data entry", "atendimento", "auxiliar"))
    return bool((juniorish or operational) and monthly_like and high >= 15_000)


def _similarity(text_a: str, text_b: str) -> float:
    text_a, text_b = _text(text_a).lower(), _text(text_b).lower()
    if not text_a or not text_b:
        return 0.0
    return difflib.SequenceMatcher(None, text_a, text_b).ratio()


def find_similar_flagged_case(
    job_text: str, historico_golpes: list[dict], threshold: float = REPOST_SIMILARITY_THRESHOLD
) -> dict | None:
    """Compara o texto da vaga nova contra cada caso já marcado como golpe.
    Retorna o melhor match acima do limiar, ou None se nenhum for parecido o
    suficiente. `historico_golpes` é injetado por quem chama (não há acesso a
    banco aqui), o que mantém evaluate_job puro e fácil de testar."""
    melhor: dict | None = None
    for caso in historico_golpes:
        texto_caso = f"{caso.get('title', '')} {caso.get('description', '')}"
        score = _similarity(job_text, texto_caso)
        if score >= threshold and (melhor is None or score > melhor["similaridade"]):
            melhor = {
                "titulo": caso.get("title") or "(sem título)",
                "criado_em": caso.get("criado_em"),
                "similaridade": round(score, 2),
            }
    return melhor


def evaluate_job(job: dict, historico_golpes: list[dict] | None = None) -> dict:
    flags: list[RedFlagResult] = []

    def add(code: str, evidence: str | None = None) -> None:
        description, weight = RED_FLAGS[code]
        flags.append(RedFlagResult(code, description, weight, evidence))

    title = _text(job.get("title"))
    description = _text(job.get("description"))
    requirements = _text(job.get("requirements"))
    benefits = _text(job.get("benefits"))
    company_profile = _text(job.get("company_profile"))
    raw_text = _text(job.get("texto_bruto"))
    combined_text = "\n".join([title, description, requirements, benefits, raw_text])

    if not bool(job.get("has_company_logo")):
        add("SEM_LOGO_EMPRESA")
    if not company_profile:
        add("SEM_PERFIL_EMPRESA")
    if len(description) < 180:
        add("DESCRICAO_CURTA", description[:120] or raw_text[:120] or None)
    if not bool(job.get("has_questions")):
        add("SEM_PERGUNTAS_TRIAGEM")

    salary_suspicious = is_salary_suspicious(
        _text(job.get("salary_range")),
        _text(job.get("required_experience")),
        _text(job.get("function")),
    )
    if salary_suspicious:
        add("SALARIO_INCOMPATIVEL", _text(job.get("salary_range")))

    education = _text(job.get("required_education")).lower()
    if salary_suspicious and education in LOW_EDUCATION:
        add("EDUCACAO_MINIMA_SALARIO_ALTO", _text(job.get("required_education")))

    suspicious_title = _contains_any(title, TITLE_KEYWORDS)
    if suspicious_title:
        add("TITULO_SUSPEITO", suspicious_title)

    payment_match = _contains_any(combined_text, PAYMENT_KEYWORDS)
    if payment_match:
        add("COBRANCA_ANTECIPADA", payment_match)

    contact = _text(job.get("canal_contato")) or combined_text
    generic_email = GENERIC_EMAIL_RE.search(contact)
    if generic_email:
        add("CANAL_GENERICO", generic_email.group(0))

    urgency_match = _contains_any(combined_text, URGENCY_KEYWORDS)
    if urgency_match:
        add("URGENCIA_EXCESSIVA", urgency_match)

    injection_match = _contains_any(combined_text, PROMPT_INJECTION_KEYWORDS)
    if injection_match:
        add("TENTATIVA_MANIPULACAO_IA", injection_match)

    repost_match = find_similar_flagged_case(f"{title} {description}", historico_golpes or [])
    if repost_match:
        evidencia = (
            f"{int(repost_match['similaridade'] * 100)}% similar a \"{repost_match['titulo']}\" "
            f"({repost_match['criado_em']})"
        )
        add("REPOSTAGEM_DE_GOLPE_CONHECIDO", evidencia)

    score = min(100, sum(flag.peso for flag in flags))
    if score >= 60:
        verdict = "provavel_golpe"
    elif score >= 30:
        verdict = "atencao"
    else:
        verdict = "provavel_legitima"

    extracted_fields = sum(1 for value in job.values() if value not in (None, "", False))
    if extracted_fields >= 12:
        confidence = "alta"
    elif extracted_fields >= 7:
        confidence = "media"
    else:
        confidence = "baixa"

    return {
        "score_risco": score,
        "veredito": verdict,
        "confianca": confidence,
        "red_flags": [asdict(flag) for flag in flags],
    }
