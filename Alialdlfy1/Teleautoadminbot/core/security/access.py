from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    reason: str
    role: str = "none"

class AccessController:
    """Small RBAC layer for sensitive control-plane operations."""
    def __init__(self, admin_check=None):
        self.admin_check = admin_check or (lambda _uid: False)
        self._roles: dict[str, set[str]] = {}

    def set_role(self, user_id, role: str):
        self._roles[str(user_id)] = {role}

    def role(self, user_id) -> str:
        uid = str(user_id)
        if self.admin_check(user_id):
            return "admin"
        roles = self._roles.get(uid, set())
        return next(iter(roles), "none")

    def authorize(self, user_id, action: str) -> AccessDecision:
        role = self.role(user_id)
        if action in {"view_metrics", "view_health", "view_queue"} and role in {"admin", "operator", "viewer"}:
            return AccessDecision(True, "allowed", role)
        if action in {"retry_dead_letter", "ack_alert"} and role in {"admin", "operator"}:
            return AccessDecision(True, "allowed", role)
        if action in {"repair", "rollback", "rotate_secrets", "change_security"} and role == "admin":
            return AccessDecision(True, "allowed", role)
        return AccessDecision(False, "admin_required" if action in {"repair", "rollback", "rotate_secrets", "change_security"} else "forbidden", role)
