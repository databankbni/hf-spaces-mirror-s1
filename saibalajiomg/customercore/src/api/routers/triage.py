"""
CustomerCore API — Triage Router (Phase 13)

Wires the Supabase persistent repository layer into the triage routes.
Replaces the in-memory triage_store with TicketRepository.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from src.api.auth import AuthenticatedTenant, require_role, verify_token
from src.api.models import (
    CustomerTier,
    HITLResumeRequest,
    TicketSubmitRequest,
    TicketSubmitResponse,
    TriageResultResponse,
    TriageStatus,
    TicketPriority,
    KBCitation,
)
from src.db.repository import TicketRepository, TicketRecord

router = APIRouter(prefix="/api/v1/triage", tags=["Triage"])


def row_to_response(row: dict[str, Any], violations: list[dict] | None = None) -> TriageResultResponse:
    """Map database ticket row dictionary to TriageResultResponse schema."""
    completed_at = row.get("completed_at") or row.get("processing_completed_at")
    if isinstance(completed_at, str):
        if completed_at.endswith("Z"):
            completed_at = completed_at[:-1] + "+00:00"
        completed_at = datetime.fromisoformat(completed_at)
    
    created_at = row.get("created_at")
    if isinstance(created_at, str):
        if created_at.endswith("Z"):
            created_at = created_at[:-1] + "+00:00"
        created_at = datetime.fromisoformat(created_at)
        
    churn_risk = row.get("churn_risk")
    if isinstance(churn_risk, (int, float)):
        score = float(churn_risk)
        if score < 0.3:
            churn_risk = "low"
        elif score < 0.6:
            churn_risk = "medium"
        elif score < 0.85:
            churn_risk = "high"
        else:
            churn_risk = "critical"
    elif churn_risk is None and row.get("churn_risk_score") is not None:
        score = float(row["churn_risk_score"])
        if score < 0.3:
            churn_risk = "low"
        elif score < 0.6:
            churn_risk = "medium"
        elif score < 0.85:
            churn_risk = "high"
        else:
            churn_risk = "critical"
            
    processing_ms = row.get("processing_ms")
    if processing_ms is None and row.get("processing_completed_at") and row.get("processing_started_at"):
        try:
            started_str = row["processing_started_at"]
            ended_str = row["processing_completed_at"]
            if started_str.endswith("Z"):
                started_str = started_str[:-1] + "+00:00"
            if ended_str.endswith("Z"):
                ended_str = ended_str[:-1] + "+00:00"
            started = datetime.fromisoformat(started_str)
            ended = datetime.fromisoformat(ended_str)
            processing_ms = int((ended - started).total_seconds() * 1000)
        except Exception:
            pass

    kb_citations_raw = row.get("kb_citations") or []
    kb_citations = []
    if isinstance(kb_citations_raw, list):
        for cit in kb_citations_raw:
            if isinstance(cit, dict):
                kb_citations.append(KBCitation(
                    citation_id=cit.get("citation_id") or cit.get("id") or "unknown",
                    relevance_score=cit.get("relevance_score") or 0.85,
                    excerpt=cit.get("excerpt") or ""
                ))
            elif isinstance(cit, KBCitation):
                kb_citations.append(cit)

    return TriageResultResponse(
        ticket_id=UUID(row["id"]) if isinstance(row["id"], str) else row["id"],
        status=TriageStatus(row["status"]),
        tenant_id=str(row["tenant_id"]),
        customer_id=row["customer_id"],
        customer_tier=CustomerTier(row.get("customer_tier", "free")),
        text=row.get("masked_text") or row.get("raw_text"),
        masked_text=row.get("masked_text") or row.get("raw_text"),
        category=row.get("category"),
        priority=TicketPriority(row["priority"]) if row.get("priority") else None,
        confidence=row.get("confidence") or 0.85,
        detected_language=row.get("detected_language"),
        suggested_resolution=row.get("suggested_resolution"),
        kb_citations=kb_citations,
        recalled_memories=row.get("recalled_memories") or [],
        churn_risk=churn_risk,
        sla_breach_risk=row.get("sla_breach_risk") if isinstance(row.get("sla_breach_risk"), bool) else (
            (row.get("sla_breach_risk") >= 0.70) if isinstance(row.get("sla_breach_risk"), (int, float)) else (
                row.get("priority") in ("high", "critical")
            )
        ),
        incident_active=row.get("incident_active") or False,
        escalation_team=row.get("escalation_team"),
        hitl_required=row.get("hitl_required") or False,
        hitl_reason=row.get("hitl_reason"),
        constitutional_blocked=not row.get("constitutional_passed", True),
        constitutional_violations=violations or [],
        created_at=created_at or datetime.utcnow(),
        completed_at=completed_at,
        processing_ms=processing_ms,
        error_message=row.get("error_message"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Background Triage Runner
# ─────────────────────────────────────────────────────────────────────────────

async def _run_triage(ticket_id: str, text: str, customer_id: str, tenant_id: str,
                      customer_tier: str, channel: str) -> None:
    """
    Background task: runs the full LangGraph 6-agent supervisor for one ticket,
    validates the output through the Constitutional Policy Engine, logs violations,
    and records the full trace in Langfuse.
    """
    from src.monitoring.langfuse_tracer import TriageTrace
    from src.responsible_ai.constitutional_policy import policy_engine
    from src.responsible_ai.privacy_vault import get_vault

    vault = get_vault()
    try:
        masked_text, _ = vault.encrypt_text(
            tenant_id=tenant_id,
            text=text,
            analyzer=None,
            anonymizer=None,
            ticket_id=ticket_id,
        )
    except Exception:
        masked_text = text

    trace = TriageTrace.start(
        ticket_id=ticket_id,
        tenant_id=tenant_id,
        customer_id=customer_id,
        customer_tier=customer_tier,
        channel=channel,
        text_preview=text[:200],
    )

    repo = TicketRepository(tenant_id)
    await repo.update_status(ticket_id, "processing")

    try:
        from src.agent.supervisor import run_triage

        with trace.agent_span("langgraph_supervisor") as sup_span:
            output = run_triage(
                ticket={
                    "body": text,
                    "customer_id": customer_id,
                    "tenant_id": tenant_id,
                    "customer_tier": customer_tier,
                    "channel": channel,
                },
                thread_id=f"thread-{ticket_id}",
            )
            result = output.model_dump() if output else {}
            sup_span.update(output=str(result)[:500] if result else "none")

        # ── Constitutional Policy Check ────────────────────────
        if isinstance(result, dict):
            resolution = result.get("suggested_resolution", "")
            if resolution:
                with trace.agent_span("constitutional_check") as policy_span:
                    # Evaluate output
                    output_verdict = policy_engine.evaluate(
                        response_text=resolution,
                        context={
                            "detected_language": result.get("detected_language", "en"),
                            "customer_tier": customer_tier,
                            "tenant_id": tenant_id,
                        },
                    )
                    
                    # Evaluate input for prompt injection / safety violations
                    input_verdict = policy_engine.evaluate(
                        response_text=text,
                        context={
                            "detected_language": result.get("detected_language", "en"),
                            "customer_tier": customer_tier,
                            "tenant_id": tenant_id,
                        },
                    )

                    # Merge verdicts: if either fails, the merged verdict fails
                    import copy
                    from src.responsible_ai.constitutional_policy import RemediationAction
                    
                    verdict = copy.deepcopy(output_verdict)
                    if not input_verdict.passed:
                        verdict.passed = False
                        verdict.score = min(verdict.score, input_verdict.score)
                        # Add input violations/warnings to the list
                        existing_ids = {v.rule_id for v in verdict.violations}
                        for v in input_verdict.violations:
                            if v.rule_id not in existing_ids:
                                verdict.violations.append(v)
                                existing_ids.add(v.rule_id)
                                
                        existing_warning_ids = {w.rule_id for w in verdict.warnings}
                        for w in input_verdict.warnings:
                            if w.rule_id not in existing_warning_ids:
                                verdict.warnings.append(w)
                                existing_warning_ids.add(w.rule_id)
                                
                        # Escalate remediation action if input is worse
                        action_priority = ["allow", "warn", "redact", "regenerate", "block"]
                        worst_action = verdict.action.value
                        if input_verdict.action.value in action_priority:
                            if action_priority.index(input_verdict.action.value) > action_priority.index(worst_action):
                                worst_action = input_verdict.action.value
                        verdict.action = RemediationAction(worst_action)
                        if verdict.action == RemediationAction.BLOCK:
                            verdict.safe_fallback = output_verdict.safe_fallback or input_verdict.safe_fallback

                    policy_span.update(output=verdict.summary())

                # Record constitutional score to Langfuse
                trace.score_constitutional(
                    verdict.score,
                    comment=verdict.summary(),
                )

                # Log violations to Supabase constitutional_violations table
                for violation in verdict.violations:
                    await repo.log_violation(
                        ticket_id=ticket_id,
                        rule_id=violation.rule_id,
                        severity=violation.severity.value,
                        action_taken=violation.action.value,
                        evidence=violation.evidence,
                        explanation=violation.explanation,
                    )

                # Apply redaction for REDACT actions
                from src.responsible_ai.constitutional_policy import RemediationAction
                for violation in verdict.violations:
                    if violation.action == RemediationAction.REDACT:
                        if violation.rule_id == "PII_PROTECTION":
                            from src.responsible_ai.constitutional_policy import (
                                _EMAIL_RE, _PHONE_RE, _SSN_RE, _IBAN_RE, _CREDIT_RE
                            )
                            resolution = _EMAIL_RE.sub("[REDACTED]", resolution)
                            resolution = _PHONE_RE.sub("[REDACTED]", resolution)
                            resolution = _SSN_RE.sub("[REDACTED]", resolution)
                            resolution = _IBAN_RE.sub("[REDACTED]", resolution)
                            resolution = _CREDIT_RE.sub("[REDACTED]", resolution)
                        elif violation.evidence:
                            import re
                            pattern = re.compile(re.escape(violation.evidence), re.IGNORECASE)
                            resolution = pattern.sub("[REDACTED]", resolution)
                result["suggested_resolution"] = resolution

                # Apply remediation fields
                result["constitutional_score"] = verdict.score
                result["constitutional_passed"] = verdict.passed
                result["constitutional_violations"] = [
                    {"rule": v.rule_id, "severity": v.severity.value,
                     "action": v.action.value, "evidence": v.evidence[:100]}
                    for v in verdict.violations
                ]

                if not verdict.passed and verdict.action.value == "block":
                    result["suggested_resolution"] = verdict.safe_fallback
                    result["constitutional_blocked"] = True

                if not verdict.passed and result.get("priority") not in ("critical", "high"):
                    result["hitl_required"] = True
                    result["hitl_reason"] = (
                        f"Constitutional violation: {verdict.violations[0].rule_name}"
                    )

        if isinstance(result, dict):
            result["customer_tier"] = customer_tier
            result["masked_text"] = masked_text

        # ── Index into Graph-RAG / Vector DB for Semantic Caching ──────────
        if isinstance(result, dict):
            try:
                import structlog
                from src.rag.graph_rag import get_engine
                engine = get_engine()
                engine.index_ticket(
                    tenant_id=tenant_id,
                    ticket_id=ticket_id,
                    text=text,
                    metadata={
                        "category": result.get("category", "general"),
                        "priority": result.get("priority", "medium"),
                        "suggested_resolution": result.get("suggested_resolution", ""),
                        "summary": result.get("summary", ""),
                    }
                )
                structlog.get_logger().info("indexed_completed_ticket_into_rag", ticket_id=ticket_id)
            except Exception as e:
                import structlog
                structlog.get_logger().warning("failed_to_index_completed_ticket_into_rag", ticket_id=ticket_id, error=str(e))

        # ── HITL or Complete ──────────────────────────────────────────────
        if isinstance(result, dict) and result.get("hitl_required"):
            result_data = {**result, "hitl_reason": result.get("hitl_reason")}
            await repo.update_status(ticket_id, "hitl", result_data=result_data)
            await repo.write_audit(
                actor="ai",
                action="ticket.escalated",
                ticket_id=ticket_id,
                details={"reason": result.get("hitl_reason", "Constitutional violation")},
            )
            trace.finish(status="hitl", output=result)
        else:
            await repo.update_status(ticket_id, "complete", result_data=result or {})
            await repo.write_audit(
                actor="ai",
                action="ticket.triaged",
                ticket_id=ticket_id,
                details={"status": "complete"},
            )
            trace.finish(status="complete", output=result)

    except Exception as exc:
        await repo.update_status(ticket_id, "failed", result_data={"error_message": str(exc)})
        await repo.write_audit(
            actor="ai",
            action="ticket.failed",
            ticket_id=ticket_id,
            details={"error": str(exc)},
        )
        trace.finish(status="failed", output={"status": "failed", "error_message": str(exc)})


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/triage — Submit a ticket for AI triage
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=TicketSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit ticket for AI triage",
    description=(
        "Accepts a support ticket and initiates async AI triage using the "
        "LangGraph 6-agent supervisor. Returns immediately with a ticket_id. "
        "Poll GET /triage/{id} for the result or subscribe to the SSE stream."
    ),
)
async def submit_ticket(
    body: TicketSubmitRequest,
    background_tasks: BackgroundTasks,
    caller: AuthenticatedTenant = Depends(verify_token),
) -> TicketSubmitResponse:
    """
    Submit a support ticket for AI triage.
    """
    ticket_id = str(uuid4())
    repo = TicketRepository(caller.tenant_id)
    
    # Mask PII in the ticket body using the zero-trust privacy vault
    from src.responsible_ai.privacy_vault import get_vault
    vault = get_vault()
    try:
        masked_text, _ = vault.encrypt_text(
            tenant_id=caller.tenant_id,
            text=body.text,
            analyzer=None,
            anonymizer=None,
            ticket_id=ticket_id,
        )
    except Exception:
        masked_text = body.text

    # Store initial ticket row in pending state
    record = TicketRecord(
        id=ticket_id,
        tenant_id=caller.tenant_id,
        customer_id=body.customer_id,
        customer_tier=body.customer_tier.value,
        channel=body.channel.value,
        raw_text=body.text,
        masked_text=masked_text,
        status="pending",
    )
    await repo.create(record)

    # Write audit log for ticket creation
    await repo.write_audit(
        actor="system",
        action="ticket.created",
        ticket_id=ticket_id,
        details={"channel": body.channel.value, "customer_tier": body.customer_tier.value},
    )

    # Attempt to publish to the Redpanda support-tickets streaming topic
    from src.streaming.producer_helper import publish_ticket_event
    
    published = publish_ticket_event(
        ticket_id=ticket_id,
        tenant_id=caller.tenant_id,
        customer_id=body.customer_id,
        customer_tier=body.customer_tier.value,
        channel=body.channel.value,
        text=body.text,
    )

    if not published:
        # Fall back to in-process background task if Redpanda is unreachable
        background_tasks.add_task(
            _run_triage,
            ticket_id=ticket_id,
            text=body.text,
            customer_id=body.customer_id,
            tenant_id=caller.tenant_id,
            customer_tier=body.customer_tier.value,
            channel=body.channel.value,
        )

    return TicketSubmitResponse(
        ticket_id=UUID(ticket_id),
        status=TriageStatus.PENDING,
        message="Ticket accepted for triage",
        estimated_seconds=3 if body.customer_tier.value in ("enterprise", "vip") else 6,
        stream_url=f"/api/v1/triage/{ticket_id}/stream",
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/triage/{ticket_id} — Poll for result
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/{ticket_id}",
    response_model=TriageResultResponse,
    summary="Get triage result",
    description="Poll for the triage result. Status progresses: pending → processing → complete/hitl/failed.",
)
async def get_triage(
    ticket_id: str,
    caller: AuthenticatedTenant = Depends(verify_token),
) -> TriageResultResponse:
    """
    Retrieve the current state of a triage request from Supabase.
    """
    repo = TicketRepository(caller.tenant_id)
    record = await repo.get(ticket_id)

    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ticket {ticket_id} not found.",
        )

    violations = []
    if not record.get("constitutional_passed", True):
        try:
            import os
            mapped_ticket_id = ticket_id
            if os.getenv("APP_ENV") != "test":
                import uuid
                try:
                    uuid.UUID(ticket_id)
                except (ValueError, AttributeError, TypeError):
                    mapped_ticket_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, ticket_id))
            
            sb = await repo._client()
            res = await sb.table("constitutional_violations").select("*").eq("ticket_id", mapped_ticket_id).execute()
            if res.data:
                violations = [
                    {
                        "rule": v.get("rule_id"),
                        "severity": v.get("severity"),
                        "action": v.get("action_taken"),
                        "evidence": v.get("evidence"),
                        "explanation": v.get("explanation"),
                    }
                    for v in res.data
                ]
        except Exception:
            pass

    return row_to_response(record, violations)


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/triage/{ticket_id}/resume — HITL Resume
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/{ticket_id}/resume",
    response_model=TriageResultResponse,
    summary="Resume a HITL-paused ticket",
    description=(
        "Resume a ticket that was paused at the Human-in-the-Loop checkpoint. "
        "Only managers and admins can call this endpoint. "
        "The operator may optionally override category, priority, or resolution."
    ),
)
async def resume_hitl(
    ticket_id: str,
    body: HITLResumeRequest,
    background_tasks: BackgroundTasks,
    caller: AuthenticatedTenant = Depends(require_role("manager", "admin")),
) -> TriageResultResponse:
    """
    Resume a HITL-paused triage with optional human overrides.
    """
    repo = TicketRepository(caller.tenant_id)
    record = await repo.get(ticket_id)

    if not record:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found.")

    if record["status"] != "hitl":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ticket {ticket_id} is not in HITL status (current: {record['status']}). "
                   f"Only HITL-paused tickets can be resumed.",
        )

    # Apply operator overrides to the stored result
    overrides_applied: dict[str, Any] = {
        "operator_id": body.operator_id,
        "operator_notes": body.operator_notes,
        "hitl_resumed_at": datetime.now(timezone.utc).isoformat(),
    }

    result = {
        "category": body.override_category or record.get("category"),
        "priority": body.override_priority.value if body.override_priority else record.get("priority"),
        "suggested_resolution": body.override_resolution or record.get("suggested_resolution"),
        "hitl_required": False,
        "hitl_reason": None,
    }

    if body.override_category:
        overrides_applied["category_overridden"] = True
    if body.override_priority:
        overrides_applied["priority_overridden"] = True
    if body.override_resolution:
        overrides_applied["resolution_overridden"] = True

    # Complete the ticket in repository
    await repo.update_status(ticket_id, "complete", result_data=result)

    # Write audit log for HITL action
    await repo.write_audit(
        actor=caller.role,
        action="hitl.approved",
        ticket_id=ticket_id,
        details={
            "operator_id": body.operator_id,
            "operator_notes": body.operator_notes,
            "overrides": overrides_applied,
        },
    )

    updated_record = await repo.get(ticket_id)
    if not updated_record:
        raise HTTPException(status_code=404, detail="Updated ticket not found.")

    return row_to_response(updated_record)


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/triage — List tickets for tenant
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=list[TriageResultResponse],
    summary="List triage results for tenant",
    description="Returns the most recent triage results for the authenticated tenant. "
                "Maximum 50 results, newest first.",
)
async def list_triages(
    caller: AuthenticatedTenant = Depends(verify_token),
    limit: int = 20,
) -> list[TriageResultResponse]:
    """
    List recent triage results for the authenticated tenant from Supabase.
    """
    limit = min(limit, 50)
    repo = TicketRepository(caller.tenant_id)
    records = await repo.list_recent(limit=limit)
    return [row_to_response(r) for r in records]
