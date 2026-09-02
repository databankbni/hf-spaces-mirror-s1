from core.ai.gateway import AIGateway
from core.providers.pool import AIProviderPool

class RateLimit(Exception):
    rate_limited = True
    cooldown_seconds = 1

def test_gateway_uses_pool_and_fails_over():
    pool = AIProviderPool({"GEMINI_KEY_1": "a", "GEMINI_KEY_2": "b"})
    calls = []
    def adapter(key, payload):
        calls.append(key)
        if key == "a":
            raise RateLimit()
        return {"ok": True, "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
    gw = AIGateway(pool, {"gemini": adapter})
    r = gw.request({"x": 1}, providers=["gemini"], max_attempts=2)
    assert r.data["ok"] is True
    assert calls == ["a", "b"]
    assert r.key_name == "GEMINI_KEY_2"
    assert r.input_tokens == 10 and r.output_tokens == 5

def test_article_package_is_one_structured_payload():
    pool = AIProviderPool({"GEMINI_KEY_1": "a"})
    seen = []
    def adapter(key, payload):
        seen.append(payload)
        return {"title": "x"}
    gw = AIGateway(pool, {"gemini": adapter})
    gw.article_package("news body")
    assert len(seen) == 1
    assert seen[0]["output_format"] == "json"
    assert "hashtags" in seen[0]["fields"]
    assert "keywords" in seen[0]["fields"]
