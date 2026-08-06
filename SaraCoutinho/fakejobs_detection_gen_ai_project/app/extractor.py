import re


EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+", re.I)
PHONE_RE = re.compile(r"(?:\+?55\s*)?(?:\(?\d{2}\)?\s*)?\d{4,5}[-\s]?\d{4}")
SALARY_RE = re.compile(r"(?:R\$\s*)?\d[\d.]{2,}(?:,\d{2})?(?:\s*(?:-|a|ate|até)\s*(?:R\$\s*)?\d[\d.]{2,}(?:,\d{2})?)?", re.I)


def normalize_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).lower() in {"1", "true", "sim", "yes", "on"}


def extract_from_text(text: str) -> dict:
    text = (text or "").strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    first_line = lines[0] if lines else ""

    email = EMAIL_RE.search(text)
    phone = PHONE_RE.search(text)
    salary = SALARY_RE.search(text)

    return {
        "title": first_line[:120],
        "description": text,
        "requirements": "",
        "benefits": "",
        "salary_range": salary.group(0) if salary else "",
        "canal_contato": email.group(0) if email else (phone.group(0) if phone else ""),
    }


def build_job_payload(form: dict) -> dict:
    extracted = extract_from_text(form.get("texto_bruto", ""))
    payload = {**extracted, **form}
    payload["telecommuting"] = normalize_bool(payload.get("telecommuting"))
    payload["has_company_logo"] = normalize_bool(payload.get("has_company_logo"))
    payload["has_questions"] = normalize_bool(payload.get("has_questions"))
    for key, value in list(payload.items()):
        if isinstance(value, str):
            payload[key] = value.strip()
    return payload
