import os
from core.providers.pool import AIProviderPool

def test_discovers_all_numbered_keys():
    env = {
        "GEMINI_KEY_1": "a",
        "GEMINI_KEY_2": "b",
        "GEMINI_KEY_7": "g",
        "GROQ_KEY_1": "c",
        "OPENROUTER_KEY_3": "d",
    }
    p = AIProviderPool(env)
    assert p.key_names("gemini") == ["GEMINI_KEY_1", "GEMINI_KEY_2", "GEMINI_KEY_7"]
    assert p.key_names("groq") == ["GROQ_KEY_1"]
    assert p.key_names("openrouter") == ["OPENROUTER_KEY_3"]

def test_rotates_least_used():
    env = {"GEMINI_KEY_1": "a", "GEMINI_KEY_2": "b"}
    p = AIProviderPool(env)
    a = p.acquire("gemini")
    b = p.acquire("gemini")
    assert {a.name, b.name} == {"GEMINI_KEY_1", "GEMINI_KEY_2"}

def test_rate_limit_cooldown_moves_to_other_key():
    env = {"GEMINI_KEY_1": "a", "GEMINI_KEY_2": "b"}
    p = AIProviderPool(env)
    a = p.acquire("gemini")
    p.report_failure(a, cooldown_seconds=60, rate_limited=True)
    b = p.acquire("gemini")
    assert b.name == "GEMINI_KEY_2"

def test_no_keys_returns_none():
    p = AIProviderPool({})
    assert p.choose(["gemini", "groq", "openrouter"]) is None
