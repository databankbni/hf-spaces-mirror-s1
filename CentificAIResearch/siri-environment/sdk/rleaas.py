"""
Minimal RLEaaS SDK client.

RLEaaS (AgentWork Simulator) exposes its SDK surface as a REST API
authenticated with SDK API keys (``rleaas_sk_…``) sent as bearer tokens.
This module wraps the endpoints needed to provision an environment
end-to-end: HF-Space import, environment record updates, and the tools /
scenarios / verifiers stores.

Usage:
    from sdk.rleaas import RLEaaSClient
    client = RLEaaSClient(api_key=os.environ["RLEAAS_API_KEY"])
    client.environments()
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

DEFAULT_BASE_URL = "https://rleaas.centific.com"


class RLEaaSError(RuntimeError):
    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"HTTP {status} from {url}: {body[:300]}")
        self.status = status
        self.body = body


class RLEaaSClient:
    def __init__(self, api_key: Optional[str] = None, base_url: str = DEFAULT_BASE_URL, timeout: int = 120):
        self.api_key = api_key or os.environ.get("RLEAAS_API_KEY", "")
        if not self.api_key:
            raise ValueError("Provide api_key or set RLEAAS_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ── plumbing ────────────────────────────────────────────────────────────
    def _request(self, method: str, path: str, payload: Any = None) -> Any:
        url = self.base_url + path
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            raise RLEaaSError(e.code, e.read().decode(errors="replace"), url) from None

    def get(self, path: str) -> Any: return self._request("GET", path)
    def post(self, path: str, payload: Any) -> Any: return self._request("POST", path, payload)
    def put(self, path: str, payload: Any) -> Any: return self._request("PUT", path, payload)

    # ── environments ────────────────────────────────────────────────────────
    def environments(self) -> List[Dict[str, Any]]:
        d = self.get("/api/environments")
        return d if isinstance(d, list) else d.get("environments", d)

    def get_environment(self, name: str) -> Optional[Dict[str, Any]]:
        return next((e for e in self.environments() if e.get("name") == name), None)

    def import_hf_space(self, name: str, hf_owner: str, hf_repo: str,
                        description: str = "", overwrite: bool = False) -> Dict[str, Any]:
        """Clone a (public) HF Space server-side and register it as an environment."""
        return self.post("/api/huggingface/import", {
            "name": name, "description": description,
            "hf_url": f"https://huggingface.co/spaces/{hf_owner}/{hf_repo}",
            "hf_owner": hf_owner, "hf_repo": hf_repo, "overwrite": overwrite,
        })

    def update_environment(self, name: str, **fields: Any) -> Dict[str, Any]:
        """Merge arbitrary fields into the env record (tools/scenarios/verifier_configs
        are also synced into the relational stores by the platform)."""
        return self.put(f"/api/custom-environments/{urllib.parse.quote(name, safe='')}", fields)

    def set_system(self, name: str, system: str) -> Dict[str, Any]:
        return self.put(f"/api/environments/{urllib.parse.quote(name, safe='')}/system", {"system": system})

    def set_category(self, name: str, category: str) -> Dict[str, Any]:
        return self.put(f"/api/environments/{urllib.parse.quote(name, safe='')}/category", {"category": category})

    # ── tools / scenarios / verifiers ───────────────────────────────────────
    def upsert_tools(self, environment: str, tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        return self.post("/api/tools", {"environment_name": environment, "tools": tools})

    def upsert_scenarios(self, environment: str, scenarios: List[Dict[str, Any]]) -> Dict[str, Any]:
        return self.post("/api/scenarios", {"product": environment, "scenarios": scenarios})

    def create_verifier(self, definition: Dict[str, Any]) -> Dict[str, Any]:
        """Upserts when `definition["id"]` is stable, so re-runs are idempotent."""
        return self.post("/api/verifiers", definition)

    def scenarios(self) -> List[Dict[str, Any]]:
        d = self.get("/api/scenarios")
        return d if isinstance(d, list) else d.get("scenarios", [])

    def tools(self, environment: Optional[str] = None) -> List[Dict[str, Any]]:
        d = self.get("/api/tools" + (f"?environment={environment}" if environment else ""))
        t = d if isinstance(d, list) else d.get("tools", [])
        if environment:
            t = [x for x in t if (x.get("environment") or "") == environment]
        return t

    def rollouts(self, environment: str) -> Dict[str, Any]:
        return self.get(f"/api/rollouts/{urllib.parse.quote(environment, safe='')}")
