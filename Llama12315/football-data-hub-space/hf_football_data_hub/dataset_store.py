from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .settings import settings


def _json_default(obj: Any):
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


class DatasetStore:
    """Local-first store with optional HF Dataset persistence.

    Free HF Spaces should not rely on local disk as the source of truth.
    This class always writes local cache first and, when HF_DATASET_REPO + HF_TOKEN
    are configured, also uploads the JSON file to the private/public Dataset repo.
    """

    def __init__(self):
        self.root = settings.data_dir
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, rel_path: str) -> Path:
        safe = rel_path.strip().lstrip("/")
        return self.root / safe

    def save_json(self, rel_path: str, payload: dict) -> dict:
        path = self._path(rel_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default)
        path.write_text(text, encoding="utf-8")
        remote = self._upload_file_if_configured(path, rel_path)
        return {
            "local_path": str(path),
            "rel_path": rel_path,
            "bytes": len(text.encode("utf-8")),
            "remote_uploaded": remote,
        }

    def load_json(self, rel_path: str, *, prefer_remote: bool = False) -> dict | None:
        path = self._path(rel_path)
        if path.exists() and not prefer_remote:
            return json.loads(path.read_text(encoding="utf-8"))

        # Market packets must check the Dataset revision on every API read; a
        # persisted Space disk cache is not evidence of current market prices.
        if settings.has_remote_dataset:
            try:
                from huggingface_hub import hf_hub_download

                downloaded = hf_hub_download(
                    repo_id=settings.hf_dataset_repo,
                    repo_type="dataset",
                    filename=rel_path,
                    token=settings.hf_token,
                    force_download=prefer_remote,
                )
                data = json.loads(Path(downloaded).read_text(encoding="utf-8"))
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                return data
            except Exception:
                return None
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None

    def packet_with_freshness(self, rel_path: str) -> tuple[dict | None, dict]:
        """Always revalidate Dataset packet metadata before serving it."""
        packet = self.load_json(rel_path, prefer_remote=True)
        if not packet:
            return None, {"eligible_for_directional_analysis": False, "reason": "packet_not_found"}
        contract = dict(packet.get("freshness_contract", {}))
        captured_at = contract.get("captured_at") or packet.get("captured_at")
        try:
            captured = datetime.fromisoformat(str(captured_at).replace("Z", "+00:00")).astimezone(timezone.utc)
            age_seconds = max(0, round((datetime.now(timezone.utc) - captured).total_seconds()))
        except (TypeError, ValueError):
            return packet, {**contract, "eligible_for_directional_analysis": False, "reason": "captured_at_invalid"}
        max_age_seconds = int(contract.get("max_age_seconds") or 0)
        origin_source_mode = str(contract.get("origin_source_mode") or packet.get("origin_source_mode") or contract.get("source_mode") or packet.get("source_mode") or "unknown")
        eligible = bool(
            origin_source_mode == "local_live_packet"
            and contract.get("live_refresh_performed") is True
            and max_age_seconds > 0
            and age_seconds <= max_age_seconds
        )
        return packet, {
            **contract,
            "source_mode": "hf_remote_packet",
            "origin_source_mode": origin_source_mode,
            "distribution_source": "hf_dataset",
            "captured_at": captured.isoformat(),
            "age_seconds": age_seconds,
            "max_age_seconds": max_age_seconds,
            "eligible_for_directional_analysis": eligible,
            "reason": "fresh_live_packet" if eligible else "stale_or_nonlive_packet",
        }

    def _upload_file_if_configured(self, path: Path, rel_path: str) -> bool:
        """Persist compact artifacts across free-Space restarts when configured."""
        if not settings.has_remote_dataset:
            return False
        try:
            from huggingface_hub import HfApi
            HfApi(token=settings.hf_token).upload_file(
                path_or_fileobj=str(path), path_in_repo=rel_path,
                repo_id=settings.hf_dataset_repo, repo_type="dataset",
                token=settings.hf_token, commit_message=f"data hub {rel_path}",
            )
            return True
        except Exception:
            return False

    @staticmethod
    def today_str() -> str:
        return date.today().isoformat()


store = DatasetStore()


def rel_hot_pool(day: str) -> str:
    return f"data/hot_match_pool/{day}.json"


def rel_crow_full_pool(day: str, slot: str) -> str:
    return f"data/crow_full_pool/{day}/{slot}.json"


def rel_crow_full_merged_pool(day: str) -> str:
    return f"data/crow_full_pool/{day}/merged.json"


def rel_packet(day: str, match_id: str) -> str:
    return f"data/compact_packets/{day}/{match_id}.json"


def rel_raw(day: str, match_id: str, name: str) -> str:
    return f"data/raw_sources/{day}/{match_id}/{name}.json"


def rel_status(day: str) -> str:
    return f"data/source_status/{day}.json"


def rel_correct_score(day: str) -> str:
    return f"data/correct_score/{day}.json"


def rel_crow_screener(day: str, match_id: str) -> str:
    return f"data/crow_screener/{day}/{match_id}.json"
