"""
MOK public autonomous production ingress.

This module owns no production authority.

Its only responsibility is to normalize an external request and
submit it to the canonical M15 autonomous runtime authority.

Canonical chain:

    public ingress
        -> M15AutonomousRuntimeAuthority
        -> MOKRuntimeAuthority
        -> canonical platform MOKNativeProductionExecutor
        -> native production

No executor, verifier, recovery controller, or production engine
is instantiated here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Sequence
from uuid import uuid4

from ai_director.creative_studio.intelligence.m15_learning.runtime.m15_autonomous_runtime_authority import M15AutonomousRuntimeAuthority


class MOKPublicAutonomousProductionBridge:
    """Zero-authority public ingress to canonical MOK autonomy."""

    VERSION = "H10.1C"
    SCHEMA = "MOK_PUBLIC_AUTONOMOUS_PRODUCTION_REQUEST_V1"
    AUTHORITY = "NONE"

    def __init__(
        self,
        runtime_authority: Optional[M15AutonomousRuntimeAuthority] = None,
    ) -> None:
        self.runtime_authority = (
            runtime_authority
            if runtime_authority is not None
            else M15AutonomousRuntimeAuthority()
        )

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _normalize_assets(
        assets: Optional[Sequence[Any]],
    ) -> list[str]:
        normalized: list[str] = []

        for asset in assets or []:
            if asset is None:
                continue

            candidate = getattr(asset, "name", asset)
            value = str(candidate).strip()

            if value:
                normalized.append(value)

        return normalized

    def build_runtime_context(
        self,
        request: str,
        assets: Optional[Sequence[Any]] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not isinstance(request, str):
            raise TypeError("request must be a string")

        normalized_request = request.strip()

        if not normalized_request:
            raise ValueError("production request cannot be empty")

        normalized_assets = self._normalize_assets(assets)

        return {
            "schema": self.SCHEMA,
            "request_id": f"mok-public-{uuid4().hex}",
            "submitted_at": self._timestamp(),
            "source": "MOK_PUBLIC_GRADIO",
            "authority": self.AUTHORITY,
            "public_request": normalized_request,
            "assets": normalized_assets,
            "metadata": dict(metadata or {}),
            "autonomous_authority_required": True,
            "public_execution_authorized": False,
            "public_recovery_authorized": False,
            "public_verification_authorized": False,
        }

    def submit(
        self,
        request: str,
        assets: Optional[Sequence[Any]] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        runtime_context = self.build_runtime_context(
            request=request,
            assets=assets,
            metadata=metadata,
        )

        result = self.runtime_authority.execute_authoritative_production(
            runtime_context
        )

        if not isinstance(result, Mapping):
            raise RuntimeError(
                "Canonical MOK authority returned a non-mapping result"
            )

        return dict(result)


def submit_public_production_request(
    request: str,
    assets: Optional[Sequence[Any]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Submit one public request to canonical autonomous MOK."""

    bridge = MOKPublicAutonomousProductionBridge()

    return bridge.submit(
        request=request,
        assets=assets,
        metadata=metadata,
    )
