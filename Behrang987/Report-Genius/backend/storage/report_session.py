"""Persisted in-memory report jobs for legacy UI compatibility."""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, TypeVar

from backend.storage import tenant_store

_lock = threading.RLock()

_T = TypeVar("_T")


def _from_stored(cls: type[_T], data: dict[str, Any]) -> _T:
    """Build a dataclass from disk JSON, ignoring unknown keys from older builds."""
    allowed = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in allowed})  # type: ignore[call-arg]


@dataclass
class UploadedDocument:
    document_id: str
    filename: str
    status: str = "complete"
    error: str | None = None
    ingested_chunks: int = 0
    storage_path: str = ""
    file_size: int = 0
    created_at: float = field(default_factory=time.time)
    content_hash: str = ""
    # Per-subsection capture summary from the last ingest (see ingest.verification).
    ingest_verification: dict | None = None
    # Canonical RAG bucket stamped at upload: "house" | "flat" | "" (legacy untagged).
    property_type: str = ""


@dataclass
class ReportSession:
    report_id: str
    tenant_id: str
    draft_id: str
    survey_level: int = 3
    primary_document_id: str = ""
    document_ids: list[str] = field(default_factory=list)
    status: str = "idle"
    error_message: str | None = None
    property_type: str = "semi-detached house"
    tenure: str = "freehold"
    generation_section_total: int | None = None
    generation_started_at: float | None = None
    sections_payload: dict[str, dict[str, Any]] = field(default_factory=dict)
    evaluation: dict[str, Any] | None = None
    interference_level: str = "medium"
    # "rics" (RICS Level 3 structure) | "content" (content-based topic mode).
    structure_mode: str = "rics"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


def _documents_path(tenant_id: str) -> Path:
    return tenant_store.tenant_root(tenant_id) / "compat_documents.json"


def _reports_dir(tenant_id: str) -> Path:
    d = tenant_store.tenant_root(tenant_id) / "compat_reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _report_path(tenant_id: str, report_id: str) -> Path:
    return _reports_dir(tenant_id) / f"{report_id}.json"


def save_document(tenant_id: str, doc: UploadedDocument) -> None:
    with _lock:
        path = _documents_path(tenant_id)
        rows: dict[str, dict] = {}
        if path.is_file():
            rows = json.loads(path.read_text(encoding="utf-8"))
        rows[doc.document_id] = asdict(doc)
        path.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def list_documents(tenant_id: str) -> dict[str, UploadedDocument]:
    path = _documents_path(tenant_id)
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k: _from_stored(UploadedDocument, v) for k, v in raw.items()}


def get_document(tenant_id: str, document_id: str) -> UploadedDocument | None:
    return list_documents(tenant_id).get(document_id)


def delete_document(tenant_id: str, document_id: str) -> bool:
    with _lock:
        path = _documents_path(tenant_id)
        if not path.is_file():
            return False
        rows: dict[str, dict] = json.loads(path.read_text(encoding="utf-8"))
        if document_id not in rows:
            return False
        del rows[document_id]
        path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        return True


def save_session(session: ReportSession) -> None:
    session.updated_at = time.time()
    with _lock:
        path = _report_path(session.tenant_id, session.report_id)
        path.write_text(json.dumps(asdict(session), indent=2), encoding="utf-8")


def load_session(tenant_id: str, report_id: str) -> ReportSession | None:
    path = _report_path(tenant_id, report_id)
    if not path.is_file():
        return None
    with _lock:
        data = json.loads(path.read_text(encoding="utf-8"))
    return _from_stored(ReportSession, data)


def create_report_session(
    tenant_id: str,
    *,
    survey_level: int,
    primary_document_id: str = "",
    document_ids: list[str] | None = None,
    structure_mode: str = "rics",
) -> ReportSession:
    from backend.domain.rics_level3_schema import PARENT_SECTION_COUNT

    mode = (structure_mode or "rics").strip().lower()
    if mode not in ("rics", "content"):
        mode = "rics"
    session = ReportSession(
        report_id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        draft_id=uuid.uuid4().hex,
        survey_level=survey_level,
        primary_document_id=primary_document_id or "",
        document_ids=list(document_ids or []),
        generation_section_total=PARENT_SECTION_COUNT,
        structure_mode=mode,
    )
    save_session(session)
    return session


def new_document_id() -> str:
    return uuid.uuid4().hex
