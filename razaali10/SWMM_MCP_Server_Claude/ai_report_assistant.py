"""Optional AI assistance for Calgary SWMR drafting and consistency review.

This module is intentionally separate from the general model-analysis agent.
The deterministic report engine remains the source of all engineering values,
criteria statuses, checklist statuses, and permitted conclusions.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import requests

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"

PROVIDERS: dict[str, dict[str, Any]] = {
    "Claude (Anthropic)": {
        "models": ["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5"],
        "format": "anthropic",
        "url": "https://api.anthropic.com/v1/messages",
    },
    "GPT (OpenAI)": {
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
        "format": "openai",
        "url": "https://api.openai.com/v1/chat/completions",
    },
    "Gemini (Google)": {
        "models": ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
        "format": "gemini",
        "url": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
    },
    "Groq (Free tier)": {
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
        "format": "openai",
        "url": "https://api.groq.com/openai/v1/chat/completions",
    },
    "Mistral": {
        "models": ["mistral-large-latest", "mistral-small-latest", "open-mistral-7b"],
        "format": "openai",
        "url": "https://api.mistral.ai/v1/chat/completions",
    },
}


def load_prompt(name: str) -> str:
    path = PROMPT_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


DRAFT_SYSTEM_PROMPT = load_prompt("calgary_report_drafting_system.txt")
REVIEW_SYSTEM_PROMPT = load_prompt("calgary_report_review_system.txt")


def _call_provider(
    provider_name: str,
    api_key: str,
    model: str,
    messages: Sequence[Mapping[str, str]],
    system_prompt: str,
    max_tokens: int = 3200,
    timeout: int = 90,
) -> str:
    if provider_name not in PROVIDERS:
        raise ValueError(f"Unsupported provider: {provider_name}")
    if not api_key.strip():
        raise ValueError("An API key is required for optional AI assistance.")

    provider = PROVIDERS[provider_name]
    fmt = provider["format"]

    if fmt == "anthropic":
        response = requests.post(
            provider["url"],
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": model,
                "max_tokens": max_tokens,
                "system": system_prompt,
                "messages": list(messages),
            },
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()["content"][0]["text"].strip()

    if fmt == "openai":
        response = requests.post(
            provider["url"],
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            json={
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system_prompt}] + list(messages),
            },
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()

    if fmt == "gemini":
        url = provider["url"].replace("{model}", model) + f"?key={api_key}"
        contents = []
        for message in messages:
            role = "model" if message["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": message["content"]}]})
        response = requests.post(
            url,
            json={
                "system_instruction": {"parts": [{"text": system_prompt}]},
                "contents": contents,
                "generationConfig": {"maxOutputTokens": max_tokens},
            },
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

    raise ValueError(f"Provider format is not implemented: {fmt}")


def _safe_json(data: Mapping[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, default=str, separators=(",", ":"))


def draft_report_section(
    *,
    provider_name: str,
    api_key: str,
    model: str,
    section: str,
    report_context: Mapping[str, Any],
    additional_instruction: str = "",
) -> str:
    """Draft narrative from deterministic report context only."""
    request = f"""Prepare this Calgary SWMR draft component: {section}.

Use only the VERIFIED_REPORT_CONTEXT JSON below. Follow every conclusion-control,
checklist, storage, outfall, minor-system, major-system, and model-input/output rule
in the system prompt. Preserve all values and units exactly.

VERIFIED_REPORT_CONTEXT:
{_safe_json(report_context)}

ADDITIONAL_USER_INSTRUCTION:
{additional_instruction.strip() or 'None'}

Return report-ready prose with clear headings. Do not include a preamble about being an AI.
"""
    return _call_provider(
        provider_name,
        api_key,
        model,
        [{"role": "user", "content": request}],
        DRAFT_SYSTEM_PROMPT,
    )


def review_report_narrative(
    *,
    provider_name: str,
    api_key: str,
    model: str,
    narrative: str,
    report_context: Mapping[str, Any],
) -> str:
    """Review narrative against deterministic facts without changing model results."""
    request = f"""Review the DRAFT_NARRATIVE against VERIFIED_REPORT_CONTEXT.
Identify unsupported claims, value or unit discrepancies, checklist omissions,
misuse of criteria, overstatements, and contradictions. Then provide corrected
replacement wording for each material issue.

VERIFIED_REPORT_CONTEXT:
{_safe_json(report_context)}

DRAFT_NARRATIVE:
{narrative}
"""
    return _call_provider(
        provider_name,
        api_key,
        model,
        [{"role": "user", "content": request}],
        REVIEW_SYSTEM_PROMPT,
    )


def draft_multiple_report_sections(*, provider_name: str, api_key: str, model: str, sections: Sequence[str], report_context: Mapping[str, Any], additional_instruction: str = "") -> dict[str, str]:
    """Generate independent section drafts so each can be reviewed and approved."""
    drafts: dict[str, str] = {}
    for section in sections:
        drafts[section] = draft_report_section(
            provider_name=provider_name, api_key=api_key, model=model, section=section,
            report_context=report_context, additional_instruction=additional_instruction,
        )
    return drafts
