from app.config import settings
import httpx
import asyncio
import logging

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_DELAY = 2  # seconds
POLLINATIONS_URL = "https://text.pollinations.ai/openai/chat/completions"


async def _post_openrouter(payload: dict, timeout: float = 60.0) -> dict:
    """POST to OpenRouter with retry on 429 / 529."""
    for attempt in range(MAX_RETRIES):
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{settings.openrouter_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=timeout,
            )
            if resp.status_code in (429, 529):
                retry_after = resp.headers.get("retry-after")
                delay = int(retry_after) if retry_after else BASE_DELAY * (2 ** attempt)
                logger.warning(f"Rate limited (attempt {attempt+1}/{MAX_RETRIES}), retrying in {delay}s")
                await asyncio.sleep(delay)
                continue
            resp.raise_for_status()
            return resp.json()
    resp.raise_for_status()
    return resp.json()


async def _call_gemini(messages: list, temperature: float = 0.3) -> str:
    """Call Google Gemini directly via REST API."""
    if not settings.gemini_api_key:
        raise RuntimeError("No Gemini API key configured")

    contents = []
    for msg in messages:
        role = "user" if msg["role"] in ("user", "system") else "model"
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent?key={settings.gemini_api_key}"
    payload = {
        "contents": contents,
        "generationConfig": {"temperature": temperature},
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]


async def _post_pollinations(messages: list, temperature: float = 0.3) -> str:
    """Fallback: use Pollinations.ai free text API (no key needed)."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            POLLINATIONS_URL,
            headers={"Content-Type": "application/json"},
            json={"model": "openai", "messages": messages, "temperature": temperature},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


async def _llm_call(messages: list, temperature: float = 0.3) -> str:
    """Try OpenRouter → Gemini → Pollinations."""
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": temperature,
    }
    try:
        data = await _post_openrouter(payload)
        return data["choices"][0]["message"]["content"]
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (429, 529):
            logger.warning("OpenRouter rate limited, trying Gemini...")
        else:
            raise

    try:
        result = await _call_gemini(messages, temperature)
        logger.info("Gemini responded successfully")
        return result
    except Exception as ex:
        logger.warning(f"Gemini failed ({ex}), falling back to Pollinations.ai")

    return await _post_pollinations(messages, temperature)


async def chat_completion(source_text: str, question: str) -> str:
    """Call LLM with grounded source material."""
    system_prompt = (
        "You are NoteStudio AI, a research assistant that answers questions "
        "strictly based on the provided source material. Rules:\n"
        "1. ONLY use information found in the source text.\n"
        "2. If the answer cannot be found in the source, say: "
        "\"I couldn't find information about that in the provided source material.\"\n"
        "3. Do NOT use your general knowledge to fill in gaps.\n"
        "4. Keep answers concise and direct.\n"
        "5. When relevant, quote or reference the specific part of the source."
    )
    user_prompt = f"<source_text>\n{source_text}\n</source_text>\n\nQuestion: {question}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return await _llm_call(messages, temperature=0.3)


async def generate_summary(source_text: str) -> str:
    """Generate a concise audio narration summary from source text."""
    prompt = (
        "Generate a concise 2-3 paragraph audio summary of the following text. "
        "Make it suitable for narration, with natural pauses and clear structure.\n\n"
        f"Text:\n\n{source_text}"
    )
    return await _llm_call([{"role": "user", "content": prompt}], temperature=0.5)


async def generate_narration_script(source_text: str) -> str:
    """Generate a 60-90 second single-narrator audio overview script."""
    system_prompt = (
        "You are an audio script writer for NoteStudio AI. "
        "Write a clear, conversational narration script for a single speaker. "
        "Rules:\n"
        "1. The script should be 60-90 seconds when read aloud (~150-220 words).\n"
        "2. Use a warm, informative tone — like a podcast host summarizing key points.\n"
        "3. Single narrator only — no dialogue, no second speaker.\n"
        "4. Include a brief intro (Here is an overview of...) and a closing thought.\n"
        "5. Use natural sentence flow; avoid bullet points or lists.\n"
        "6. Return ONLY the narration script, nothing else."
    )
    user_prompt = f"<source_text>\n{source_text}\n</source_text>"
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return await _llm_call(messages, temperature=0.5)


async def generate_image_prompt(source_text: str) -> str:
    """Generate a descriptive image prompt from source text."""
    prompt = (
        "Based on the following text, generate a short, descriptive image prompt "
        "that would make a good illustrative image. Return ONLY the prompt, nothing else.\n\n"
        f"Text:\n\n{source_text}"
    )
    return await _llm_call([{"role": "user", "content": prompt}], temperature=0.7)
