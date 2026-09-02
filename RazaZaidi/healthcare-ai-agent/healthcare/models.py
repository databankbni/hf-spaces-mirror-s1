import os
import time
from functools import lru_cache
from dotenv import load_dotenv

load_dotenv()

GROQ_KEY    = os.getenv("GROQ_API_KEY")
GEMINI_KEY  = os.getenv("GOOGLE_API_KEY")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")

# Groq shut down Llama 3.x on free/developer tier on 2026-08-16.
# See: https://console.groq.com/docs/deprecations
DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"
DEPRECATED_GROQ_MODELS = {
    "llama-3.3-70b-versatile": "openai/gpt-oss-120b",
    "llama-3.1-8b-instant": "openai/gpt-oss-20b",
    "llama-3.1-70b-versatile": "openai/gpt-oss-120b",
    "llama3-70b-8192": "openai/gpt-oss-120b",
    "llama3-8b-8192": "openai/gpt-oss-20b",
    "qwen/qwen3-32b": "openai/gpt-oss-120b",
    "meta-llama/llama-4-scout-17b-16e-instruct": "openai/gpt-oss-120b",
}


def _resolve_groq_model(model_id: str | None) -> str:
    """Pick a live Groq model, remapping retired IDs from env/secrets."""
    requested = (model_id or DEFAULT_GROQ_MODEL).strip()
    if not requested:
        requested = DEFAULT_GROQ_MODEL
    replacement = DEPRECATED_GROQ_MODELS.get(requested)
    if replacement:
        print(f"Groq model '{requested}' is retired; using '{replacement}' instead.")
        return replacement
    return requested


GROQ_MODEL = _resolve_groq_model(os.getenv("GROQ_MODEL"))

DEFAULT_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "25"))
DEFAULT_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "4096"))


@lru_cache(maxsize=12)
def _cached_llm(provider: str, agent_type: str, temperature: float, model_name: str = ""):
    """Create and cache model clients to avoid rebuilding them every request."""
    if provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(
            model=model_name or GROQ_MODEL,
            temperature=temperature,
            api_key=GROQ_KEY,
            max_retries=1,
            max_tokens=DEFAULT_MAX_TOKENS,
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model="gemini-2.0-flash-lite",
            temperature=temperature,
            google_api_key=GEMINI_KEY,
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )

    if provider == "openrouter":
        from langchain_community.chat_models import ChatOpenAI
        return ChatOpenAI(
            model="mistralai/mistral-7b-instruct:free",
            temperature=temperature,
            api_key=OPENROUTER_KEY,
            base_url="https://openrouter.ai/api/v1",
            request_timeout=DEFAULT_TIMEOUT_SECONDS,
            max_retries=1,
            max_tokens=DEFAULT_MAX_TOKENS,
        )

    raise ValueError(f"Unsupported provider: {provider}")


def get_llm(temperature=0.7, agent_type="general"):
    """
    Smart model loader with per-agent temperature.
    agent_type options: triage, researcher, lifestyle, general
    """

    # Per-agent temperature (Phase 2 Lesson 4)
    agent_temperatures = {
        "triage":     0.3,  # Precise routing decisions
        "researcher": 0.4,  # Factual academic responses
        "lifestyle":  0.8,  # Warm friendly coaching
        "general":    0.7,  # Balanced responses
    }

    # Use agent-specific temp if not overridden
    if temperature == 0.7 and agent_type in agent_temperatures:
        temperature = agent_temperatures[agent_type]

    # Try Groq first (fastest and free)
    if GROQ_KEY:
        try:
            llm = _cached_llm("groq", agent_type, temperature, GROQ_MODEL)
            print(f"Using Groq ({GROQ_MODEL}) | Agent: {agent_type} | Temp: {temperature}")
            return llm
        except Exception as e:
            print(f"Groq failed: {str(e)[:50]}")
            time.sleep(0.3)

    # Try Gemini second
    if GEMINI_KEY:
        try:
            llm = _cached_llm("gemini", agent_type, temperature, "")
            print(f"Using Gemini | Agent: {agent_type} | Temp: {temperature}")
            return llm
        except Exception as e:
            print(f"Gemini failed: {str(e)[:50]}")
            time.sleep(0.3)

    # Try OpenRouter last
    if OPENROUTER_KEY:
        try:
            llm = _cached_llm("openrouter", agent_type, temperature, "")
            print(f"Using OpenRouter | Agent: {agent_type} | Temp: {temperature}")
            return llm
        except Exception as e:
            print(f"OpenRouter failed: {str(e)[:50]}")

    raise ValueError("All models failed! Check API keys in .env file")

def get_fast_llm():
    """Lightweight fast model for quick responses."""
    return get_llm(temperature=0.3, agent_type="triage")
