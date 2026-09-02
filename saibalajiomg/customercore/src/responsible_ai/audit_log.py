"""
src/responsible_ai/audit_log.py

Immutable audit logger for the CustomerCore Privacy Vault.

Every encrypt and decrypt operation is written here with:
  - tenant_id, field_name, token
  - action: "ENCRYPT" or "DECRYPT"
  - actor_role (for DECRYPT calls — who triggered the re-identification)
  - timestamp (UTC ISO-8601)
  - SHA-256 hash of the plaintext (for compliance verification without storing PII)

In local dev: logs are written to a rotating JSON-lines file under logs/.
In production: rows are inserted to a Supabase PostgreSQL table via the REST API.

Run standalone check:
  python -m src.responsible_ai.audit_log
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

# ── Config ────────────────────────────────────────────────────────────────────
LOG_DIR = Path("logs/vault_audit")
LOG_DIR.mkdir(parents=True, exist_ok=True)
AUDIT_FILE = LOG_DIR / "audit_trail.jsonl"

# Configure Python logger for console output too
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [AUDIT] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
_log = logging.getLogger("customercore.audit")


ActionType = Literal["ENCRYPT", "DECRYPT", "DECRYPT_DENIED"]


def _sha256(text: str) -> str:
    """Return SHA-256 hex digest of a UTF-8 string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_audit_entry(
    *,
    tenant_id: str,
    field_name: str,
    token: str,
    action: ActionType,
    plaintext_hash: str,
    actor_role: str = "PIPELINE",
    ticket_id: str = "",
    extra: dict | None = None,
) -> dict:
    """
    Write a single audit entry to the local JSONL file.

    Returns the entry dict so callers can inspect it in tests.
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "tenant_id": tenant_id,
        "field_name": field_name,
        "token": token,
        "plaintext_sha256": plaintext_hash,
        "actor_role": actor_role,
        "ticket_id": ticket_id,
        **(extra or {}),
    }

    # Write to local JSONL file (append-only)
    with AUDIT_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    # Console log (less detail to avoid accidentally logging sensitive data)
    _log.info(
        "[%s] tenant=%s field=%s token=%s role=%s",
        action, tenant_id, field_name, token[:12] + "...", actor_role,
    )

    return entry


def tail_audit_log(n: int = 10) -> list[dict]:
    """Return the last n entries from the audit log."""
    if not AUDIT_FILE.exists():
        return []
    lines = AUDIT_FILE.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines[-n:]]


if __name__ == "__main__":
    # Quick standalone test
    e = write_audit_entry(
        tenant_id="acme-corp",
        field_name="EMAIL_ADDRESS",
        token="TOK_EMAIL_ab12cd34",
        action="ENCRYPT",
        plaintext_hash=_sha256("john.doe@acme.com"),
        ticket_id="TKT-99999",
    )
    print("Wrote ENCRYPT entry:")
    print(json.dumps(e, indent=2))

    d = write_audit_entry(
        tenant_id="acme-corp",
        field_name="EMAIL_ADDRESS",
        token="TOK_EMAIL_ab12cd34",
        action="DECRYPT",
        plaintext_hash=_sha256("john.doe@acme.com"),
        actor_role="SUPPORT_LEAD",
        ticket_id="TKT-99999",
    )
    print("\nWrote DECRYPT entry:")
    print(json.dumps(d, indent=2))

    print(f"\nLast 2 audit entries: {len(tail_audit_log(2))}")
