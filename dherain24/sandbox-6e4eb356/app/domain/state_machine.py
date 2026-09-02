from enum import Enum
from typing import Dict, Set, Optional, Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import RecoveryCase, AuditLog

class CaseState(str, Enum):
    DETECTED = "DETECTED"
    INVESTIGATING = "INVESTIGATING"
    DECISION_READY = "DECISION_READY"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    RECOVERED = "RECOVERED"
    FAILED = "FAILED"
    ESCALATED = "ESCALATED"
    NO_ACTION = "NO_ACTION"
    CLOSED = "CLOSED"

# Strict transition map enforcing bounded execution
VALID_TRANSITIONS: Dict[CaseState, Set[CaseState]] = {
    CaseState.DETECTED: {
        CaseState.INVESTIGATING,
        CaseState.ESCALATED,
    },
    CaseState.INVESTIGATING: {
        CaseState.DECISION_READY,
        CaseState.NO_ACTION,
        CaseState.ESCALATED,
    },
    CaseState.DECISION_READY: {
        CaseState.APPROVED,
        CaseState.ESCALATED,
        CaseState.NO_ACTION,
    },
    CaseState.APPROVED: {
        CaseState.EXECUTING,
        CaseState.VERIFYING,
        CaseState.RECOVERED,
        CaseState.FAILED,
    },
    CaseState.EXECUTING: {
        CaseState.VERIFYING,
        CaseState.RECOVERED,
        CaseState.FAILED,
        CaseState.ESCALATED,
    },
    CaseState.VERIFYING: {
        CaseState.RECOVERED,
        CaseState.FAILED,
        CaseState.ESCALATED,
    },
    CaseState.NO_ACTION: {
        CaseState.CLOSED,
    },
    CaseState.RECOVERED: {
        CaseState.CLOSED,
    },
    CaseState.FAILED: {
        CaseState.CLOSED,
        CaseState.INVESTIGATING,  # Permitted retry exploration
    },
    CaseState.ESCALATED: {
        CaseState.APPROVED,  # Human approved action
        CaseState.NO_ACTION,  # Human held action
        CaseState.CLOSED,
    },
    CaseState.CLOSED: set(),  # Terminal state
}

class InvalidStateTransitionError(ValueError):
    def __init__(self, current_state: str, target_state: str, case_id: str):
        super().__init__(
            f"Invalid transition for case '{case_id}': cannot move from '{current_state}' to '{target_state}'."
        )
        self.current_state = current_state
        self.target_state = target_state
        self.case_id = case_id

async def transition_case(
    session: AsyncSession,
    case: RecoveryCase,
    target_state: CaseState,
    reason: str,
    metadata: Optional[Dict[str, Any]] = None,
    agent_run_id: Optional[str] = None,
) -> RecoveryCase:
    current = CaseState(case.status)
    target = CaseState(target_state)

    # Validate transition
    if target not in VALID_TRANSITIONS.get(current, set()):
        raise InvalidStateTransitionError(
            current_state=current.value,
            target_state=target.value,
            case_id=case.id,
        )

    # Update case state
    old_state = case.status
    case.status = target.value

    # Record immutable audit log
    audit_entry = AuditLog(
        case_id=case.id,
        agent_run_id=agent_run_id,
        event_type="STATE_TRANSITION",
        payload={
            "from_state": old_state,
            "to_state": target.value,
            "reason": reason,
            "metadata": metadata or {},
        },
    )
    session.add(audit_entry)
    await session.commit()

    return case
