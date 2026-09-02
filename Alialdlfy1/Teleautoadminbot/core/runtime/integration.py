from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from core.content_pipeline import ContentGate
from core.content.dedup import DedupStore
from core.infra.audit import AuditLog
from core.infra.metrics import Metrics
from core.jobs.queue import ProcessingQueue
from core.pipeline.adapter import SectionPipelineAdapter
from core.providers.pool import AIProviderPool
from core.ai.gateway import AIGateway
from core.publishing.ledger import PublishLedger
from core.publishing.publisher import IdempotentPublisher
from core.health.monitor import HealthMonitor
from core.repair.engine import AutoRepairEngine
from core.repair.policy import RepairGuard, RepairPolicy
from core.repair.guarded import GuardedRepair
from core.sections.base import SectionConfig
from core.sections.registry import SectionRegistry
from core.runtime.state_store import RuntimeStateStore
from core.control.plane import ControlPlane
from core.security.secret_registry import SecretRegistry
from core.security.hardening import SecurityHardener


@dataclass
class RuntimeResult:
    status: str
    stage: str
    reason: str = ""
    data: Any = None
    fingerprint: str = ""
    job_id: str = ""


@dataclass
class SectionRuntimeState:
    enabled: bool = True
    blocked_words: list[str] = field(default_factory=list)
    duplicate_protection: bool = True
    ai_enabled: bool = True
    auto_repair_enabled: bool = True
    sources: list[str] = field(default_factory=list)


class RuntimeIntegration:
    """The phase-15 composition root.

    Every section uses the same ordered runtime:
    gate -> normalization -> durable queue -> AI gateway -> validation ->
    idempotent publisher -> health/audit/metrics.

    External Telegram/Blogger implementations are injected as adapters so the
    core remains testable and future sections do not require core edits.
    """

    def __init__(
        self,
        db: Any = None,
        *,
        db_path: str = "data/p29_runtime.sqlite3",
        project_root: str = ".",
        blocked_words: Optional[list[str]] = None,
        ai_gateway: Optional[AIGateway] = None,
        queue: Optional[ProcessingQueue] = None,
        publisher: Optional[IdempotentPublisher] = None,
        health: Optional[HealthMonitor] = None,
        metrics: Optional[Metrics] = None,
        audit: Optional[AuditLog] = None,
        auto_repair: Optional[GuardedRepair] = None,
        repair_proposer: Optional[Callable[[str, dict], Optional[str]]] = None,
    ):
        self.db = db
        self.db_path = db_path
        self.state_store = RuntimeStateStore(db_path)
        self.queue = queue or ProcessingQueue(db_path)
        self.pool = ai_gateway.pool if ai_gateway else AIProviderPool()
        self.ai = ai_gateway or AIGateway(self.pool)
        self.ledger = publisher.ledger if publisher else PublishLedger(db_path)
        self.publisher = publisher or IdempotentPublisher(self.ledger, {})
        self.health = health or HealthMonitor()
        self.metrics = metrics or Metrics()
        self.audit = audit or AuditLog("data/audit.jsonl")
        self.secret_registry = SecretRegistry()
        self.security = SecurityHardener(self.secret_registry)
        self.security.refresh()
        if auto_repair is None:
            policy = RepairPolicy(
                enabled=True,
                auto_apply_low_risk=False,
                require_admin_for_medium=True,
                require_admin_for_high=True,
            )
            engine = AutoRepairEngine(project_root)
            guard = RepairGuard(policy)
            auto_repair = GuardedRepair(engine, guard)
        self.auto_repair = auto_repair
        self.repair_proposer = repair_proposer
        self.health.on_unhealthy = self._on_unhealthy

        self._gates: dict[str, ContentGate] = {}
        self._sections: dict[str, SectionRuntimeState] = {
            "blogger": SectionRuntimeState(),
            "news": SectionRuntimeState(),
            "sports": SectionRuntimeState(),
        }
        self._load_section_state()
        self._publisher_adapters: dict[str, Callable] = {}
        self._section_pipelines: dict[str, SectionPipelineAdapter] = {}
        self._repair_enabled = bool(self.state_store.get("control:auto_repair", True))
        self.control_plane = ControlPlane(self)
        self._register_health()

    def _load_section_state(self) -> None:
        for section, default in list(self._sections.items()):
            raw = self.state_store.get(f"section:{section}", {}) or {}
            if not isinstance(raw, dict):
                continue
            for key in ("enabled", "blocked_words", "duplicate_protection", "ai_enabled", "auto_repair_enabled", "sources"):
                if key in raw:
                    setattr(default, key, raw[key])

    def _persist_section_state(self, section: str) -> None:
        state = self._sections[section]
        self.state_store.set(f"section:{section}", {
            "enabled": bool(state.enabled),
            "blocked_words": list(state.blocked_words),
            "duplicate_protection": bool(state.duplicate_protection),
            "ai_enabled": bool(state.ai_enabled),
            "auto_repair_enabled": bool(state.auto_repair_enabled),
            "sources": list(state.sources),
        })

    def _register_health(self) -> None:
        for section in self._sections:
            self.health.register(
                f"section:{section}",
                lambda section=section: self._section_health(section),
            )
        for provider in self.pool.providers():
            self.health.register(
                f"provider:{provider}",
                lambda provider=provider: self._provider_health(provider),
            )

    def _section_health(self, section: str) -> dict:
        state = self._sections[section]
        return {
            "enabled": state.enabled,
            "queue": self.queue.store.get_stats(),
            "ai_enabled": state.ai_enabled,
        }

    def _provider_health(self, provider: str) -> dict:
        snap = self.pool.snapshot().get(provider, [])
        if not snap:
            raise RuntimeError("no provider keys available")
        available = [x for x in snap if x["cooldown"] <= 0]
        if not available:
            raise RuntimeError("all provider keys are in cooldown")
        return {"keys": len(snap), "available_keys": len(available)}

    def register_ai_provider(self, provider: str, adapter: Callable) -> None:
        self.ai.register(provider, adapter)
        self.health.register(
            f"provider:{provider.lower()}",
            lambda provider=provider.lower(): self._provider_health(provider),
        )

    def register_publisher(self, target: str, adapter: Callable) -> None:
        self._publisher_adapters[target] = adapter
        self.publisher.adapters[target] = adapter

    def set_section_state(self, section: str, **changes) -> SectionRuntimeState:
        state = self._sections.setdefault(section, SectionRuntimeState())
        for key, value in changes.items():
            if not hasattr(state, key):
                raise KeyError(key)
            setattr(state, key, value)
        self._gates.pop(section, None)
        self._section_pipelines.pop(section, None)
        self._persist_section_state(section)
        self._audit("section.state_changed", section=section, changes=changes)
        return state

    def get_section_state(self, section: str) -> dict:
        state = self._sections.setdefault(section, SectionRuntimeState())
        return {
            "section": section,
            "enabled": state.enabled,
            "blocked_words": list(state.blocked_words),
            "duplicate_protection": state.duplicate_protection,
            "ai_enabled": state.ai_enabled,
            "auto_repair_enabled": state.auto_repair_enabled,
            "sources": list(state.sources),
        }

    def _gate(self, section: str) -> ContentGate:
        if section not in self._gates:
            words = list(self._sections.setdefault(section, SectionRuntimeState()).blocked_words)
            state = self._sections.setdefault(section, SectionRuntimeState())
            self._gates[section] = ContentGate(
                _OverlayGateDB(self.db, words, section),
                dedup=DedupStore(self.db_path) if state.duplicate_protection else None,
            )
        return self._gates[section]

    def ingest(
        self,
        section: str,
        article: str,
        article_id: str,
        *,
        source: str = "",
        source_url: str = "",
        channel_id: str = "",
        target: str = "",
        metadata: Optional[dict] = None,
    ) -> RuntimeResult:
        state = self._sections.setdefault(section, SectionRuntimeState())
        if not state.enabled:
            self.metrics.inc(f"{section}.rejected.disabled")
            return RuntimeResult("rejected", "section", "section_disabled")
        if state.sources and source and source not in state.sources:
            self.metrics.inc(f"{section}.rejected.source")
            self._audit("content.rejected", section=section, article_id=article_id, reason="source_not_allowed")
            return RuntimeResult("rejected", "source", "source_not_allowed")
        if state.sources and not source:
            self.metrics.inc(f"{section}.rejected.source")
            return RuntimeResult("rejected", "source", "source_required")

        gate = self._gate(section)
        # Blocked words are evaluated before fingerprint/dedup and therefore before
        # queue/AI/API usage.
        verdict = gate.preflight(article, source_url, channel_id, source=source, article_id=article_id)
        if not verdict.allowed:
            self.metrics.inc(f"{section}.rejected.{verdict.reason}")
            self._audit(
                "content.rejected",
                section=section,
                article_id=article_id,
                reason=verdict.reason,
                matched=list(verdict.matched),
            )
            return RuntimeResult(
                "rejected", "gate", verdict.reason,
                fingerprint=verdict.fingerprint,
            )

        cleaned = self._clean_for_queue(article, channel_id)
        if not cleaned:
            self.metrics.inc(f"{section}.rejected.empty_after_cleanup")
            self._audit("content.rejected", section=section, article_id=article_id, reason="empty_after_cleanup")
            return RuntimeResult("rejected", "cleanup", "empty_after_cleanup", fingerprint=verdict.fingerprint)
        scoped_id = f"{section}:{article_id}"
        payload = {
            "section": section,
            "article_id": scoped_id,
            "source": source,
            "source_url": source_url,
            "channel_id": channel_id,
            "target": target or section,
            "article": cleaned,
            "fingerprint": verdict.fingerprint,
            "metadata": metadata or {},
        }
        try:
            job_id = self.queue.enqueue_article(scoped_id, payload)
        except Exception:
            # A failed queue write must not leave a permanently reserved dedup
            # record in the persistent gate.
            try:
                gate.dedup.forget(verdict.fingerprint)
            except Exception:
                pass
            self.metrics.inc(f"{section}.queue.error")
            self._audit("queue.enqueue_failed", section=section, article_id=article_id)
            raise

        self.metrics.inc(f"{section}.queued")
        self._audit(
            "content.queued",
            section=section,
            article_id=article_id,
            fingerprint=verdict.fingerprint,
            job_id=job_id,
        )
        return RuntimeResult(
            "queued", "queue", data=payload,
            fingerprint=verdict.fingerprint, job_id=job_id,
        )

    def _clean_for_queue(self, text: str, channel_id: str = "") -> str:
        """Apply deterministic removal terms only after the zero-AI gate."""
        terms = []
        if self.db is not None:
            try:
                terms.extend(self.db.get_global_remove_terms() or [])
            except Exception:
                pass
            if channel_id:
                try:
                    terms.extend(self.db.get_channel_delete_terms(channel_id) or [])
                except Exception:
                    pass
        for raw in terms:
            term = str(raw or "").strip()
            if term:
                text = text.replace(term, "")
        return text.strip()

    def process_payload(self, payload: dict) -> RuntimeResult:
        section = payload["section"]
        state = self._sections.setdefault(section, SectionRuntimeState())
        if not state.enabled:
            return RuntimeResult("rejected", "section", "section_disabled")

        if not state.ai_enabled:
            return RuntimeResult("rejected", "ai", "ai_disabled")

        text = payload["article"]
        try:
            response = self.ai.article_package(
                text,
                task=f"process_{section}_article",
            )
            data = response.data
            if not isinstance(data, dict):
                raise RuntimeError("AI returned non-object article package")
            self.metrics.inc(f"{section}.ai.success")
            self.metrics.inc(f"provider.{response.provider}.success")
        except Exception as exc:
            self.metrics.inc(f"{section}.ai.failure")
            self._audit("ai.failure", section=section, error=str(exc))
            raise

        # The same gate runs after AI so generated content cannot bypass safety.
        gate = self._gate(section)
        article = dict(data)
        article["source_url"] = payload.get("source_url", "")
        article["fingerprint"] = payload.get("fingerprint", "")
        post = gate.postflight(article, payload.get("channel_id", ""))
        if not post.allowed:
            self.metrics.inc(f"{section}.rejected.postflight")
            self._audit(
                "content.postflight_rejected",
                section=section,
                reason=post.reason,
                matched=list(post.matched),
            )
            return RuntimeResult("rejected", "validation", post.reason, fingerprint=post.fingerprint)

        article["_runtime"] = {
            "section": section,
            "article_id": payload["article_id"],
            "target": payload.get("target") or section,
            "fingerprint": payload.get("fingerprint", ""),
        }
        self.metrics.inc(f"{section}.validated")
        return RuntimeResult("validated", "validation", data=article, fingerprint=payload.get("fingerprint", ""))

    def publish_payload(self, payload: dict) -> RuntimeResult:
        article = payload["article"]
        meta = article.get("_runtime", {})
        target = payload.get("target") or meta.get("target") or payload.get("section")
        article_id = meta.get("article_id") or payload.get("article_id")
        content = self._article_content(article)

        try:
            result = self.publisher.publish(
                target, article_id, content,
                article=article,
                section=payload.get("section"),
            )
        except Exception as exc:
            self.metrics.inc(f"{payload.get('section','unknown')}.publish.failure")
            self._audit("publish.failure", section=payload.get("section"), error=str(exc))
            raise

        self.metrics.inc(f"{payload.get('section','unknown')}.publish.{result.get('status','unknown')}")
        self._audit(
            "publish.result",
            section=payload.get("section"),
            article_id=article_id,
            status=result.get("status"),
            remote_id=result.get("remote_id"),
        )
        return RuntimeResult(result.get("status", "unknown"), "publisher", data=result)

    @staticmethod
    def _article_content(article: dict) -> str:
        # Keep a stable representation for idempotency hashing while allowing
        # adapters to consume the structured article through the `article=` kwarg.
        for key in ("body", "article", "content", "text"):
            if article.get(key):
                return str(article[key])
        return str(article)

    def handle_job(self, payload: dict, job: Optional[dict] = None) -> RuntimeResult:
        """Worker handler: queue -> AI -> validation -> publisher.

        The persistent queue's retry/failure policy handles worker crashes. Publish
        idempotency is checked inside IdempotentPublisher before the remote call.
        """
        processed = self.process_payload(payload)
        if processed.status != "validated":
            return processed
        payload = dict(payload)
        payload["article"] = processed.data
        published = self.publish_payload(payload)
        return published

    def build_concurrent_workers(self, workers: int = 2, worker_lease_timeout: float = 300):
        """Build a bounded concurrent worker pool on the canonical persistent queue."""
        from core.jobs.concurrency import ConcurrentWorkers
        return ConcurrentWorkers(self.queue.store, self.worker_handlers(), workers=workers, lease_timeout=worker_lease_timeout)

    def load_snapshot(self) -> dict:
        """Safe operational load snapshot; no article payloads are exposed."""
        return {
            "queue": self.queue.store.get_stats(),
            "workers": {"supported": True, "max_concurrency": 32},
            "metrics": self.metrics.detailed_snapshot(),
        }

    def build_worker(self, worker_id: Optional[str] = None):
        from core.jobs.worker import JobWorker
        return JobWorker(self.queue.store, self.worker_handlers(), worker_id=worker_id)

    def worker_handlers(self) -> dict[str, Callable]:
        return {"article.process": self.handle_job}

    def build_section_adapter(self, section: str) -> SectionPipelineAdapter:
        if section not in self._section_pipelines:
            self._section_pipelines[section] = SectionPipelineAdapter(
                section,
                self._gate(section),
                self.queue,
                self.ai,
                self.publisher,
            )
        return self._section_pipelines[section]

    def health_snapshot(self) -> dict:
        return self.health.snapshot()

    def metrics_snapshot(self) -> dict:
        return self.metrics.snapshot()

    def control_snapshot(self) -> dict:
        return {
            "sections": {k: self.get_section_state(k) for k in self._sections},
            "health": self.health_snapshot(),
            "metrics": self.metrics_snapshot(),
            "metrics_detailed": self.metrics.detailed_snapshot(),
            "providers": self.pool.snapshot(),
            "queue": self.queue.store.get_stats(),
            "alerts": self.control_plane.evaluate(),
            "auto_repair": {
                "enabled": self._repair_enabled,
                "policy": self.auto_repair.guard.policy.__dict__,
            },
        }

    def set_auto_repair(self, enabled: bool) -> dict:
        self._repair_enabled = bool(enabled)
        self.state_store.set("control:auto_repair", self._repair_enabled)
        self._audit("repair.toggled", enabled=self._repair_enabled)
        return {"ok": True, "enabled": self._repair_enabled}

    def operational_snapshot(self) -> dict:
        return self.control_plane.snapshot()

    def recent_audit(self, limit: int = 50) -> list[dict]:
        return self.audit.recent(limit)

    def acknowledge_alert(self, key: str, *, admin_approved=False) -> dict:
        return self.control_plane.acknowledge(key, admin_approved=admin_approved)

    def queue_snapshot(self, status: str | None = None, limit: int = 50) -> list[dict]:
        rows = self.queue.store.list_jobs(status=status, limit=limit)
        # Keep control-plane output safe: do not expose arbitrary payload content.
        return [{
            "id": row.get("id"), "kind": row.get("kind"), "status": row.get("status"),
            "attempts": row.get("attempts"), "available_at": row.get("available_at"),
            "claimed_at": row.get("claimed_at"), "worker_id": row.get("worker_id"),
            "last_error": row.get("last_error", ""),
        } for row in rows]

    def requeue_dead_job(self, job_id: str, *, admin_approved: bool = False) -> dict:
        if not admin_approved:
            return {"ok": False, "reason": "admin_required"}
        ok = self.queue.store.requeue_dead(job_id)
        self._audit("queue.dead_requeued", job_id=job_id, ok=ok)
        return {"ok": ok, "job_id": job_id}

    def _on_unhealthy(self, name: str, service) -> None:
        self.metrics.inc("health.unhealthy")
        self._audit("health.unhealthy", service=name, failures=service.consecutive_failures)
        if not self._repair_enabled or not self.repair_proposer:
            return
        if name.startswith("section:"):
            section = name.split(":", 1)[1]
            if not self._sections.get(section, SectionRuntimeState()).auto_repair_enabled:
                return
        try:
            patch = self.repair_proposer(name, service.__dict__.copy())
            if not patch:
                return
            record = self.auto_repair.test_and_apply(
                f"health:{name}",
                patch,
                tests=["tests/v29"],
                admin_approved=False,
            )
            self._audit(
                "repair.result",
                service=name,
                repair_id=record.repair_id,
                status=record.status,
                reason=record.reason,
            )
        except Exception as exc:
            self._audit("repair.failure", service=name, error=str(exc))

    def monitor_once(self) -> dict:
        result = self.health.check_all()
        for name, service in result.items():
            if service.status == "unhealthy":
                self.metrics.inc("health.unhealthy")
        return self.health_snapshot()

    def _audit(self, event: str, **data) -> None:
        # AuditLog redacts string values. No raw key/token is intentionally passed.
        self.audit.write(event, **data)


class _OverlayGateDB:
    def __init__(self, legacy, words, section):
        self.legacy = legacy
        self.words = list(words)
        self.section = section

    def get_blocked_words(self):
        out = list(self.words)
        if self.legacy is not None:
            try:
                out.extend(self.legacy.get_blocked_words() or [])
            except Exception:
                pass
        return list(dict.fromkeys(out))

    def get_channel_blocked_words(self, channel_id):
        if self.legacy is not None:
            try:
                return self.legacy.get_channel_blocked_words(channel_id) or []
            except Exception:
                pass
        return []

    def is_published(self, fp):
        if self.legacy is not None:
            try:
                return bool(self.legacy.is_published(fp))
            except Exception:
                pass
        return False

    def get_article(self, fp):
        if self.legacy is not None:
            try:
                return self.legacy.get_article(fp)
            except Exception:
                pass
        return None

    def get_all_articles(self):
        if self.legacy is not None:
            try:
                return self.legacy.get_all_articles() or []
            except Exception:
                pass
        return []


class _MemoryGateDB:
    """Minimal DB contract used by isolated runtime tests."""

    def __init__(self, words):
        self.words = list(words)
        self.articles = {}
        self.published = set()

    def get_blocked_words(self):
        return self.words

    def get_channel_blocked_words(self, channel_id):
        return []

    def is_published(self, fp):
        return fp in self.published

    def get_article(self, fp):
        return self.articles.get(fp)

    def get_all_articles(self):
        return list(self.articles.values())
