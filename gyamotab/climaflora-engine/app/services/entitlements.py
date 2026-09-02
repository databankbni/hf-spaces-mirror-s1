from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum


class Plan(StrEnum):
    FREE = "FREE"
    PLUS = "PLUS"
    PRO = "PRO"


ACTIVE_SUBSCRIPTION_STATUSES = frozenset({"active", "trialing"})


@dataclass(frozen=True)
class Entitlements:
    plan: Plan
    saved_projects: int
    saved_sites: int
    comparisons: int
    monthly_exports: int
    advanced_scenarios: bool
    advanced_exports: bool
    commercial_use: bool

    def public_dict(self) -> dict[str, object]:
        return asdict(self)


ENTITLEMENTS = {
    Plan.FREE: Entitlements(Plan.FREE, 1, 1, 0, 0, False, False, False),
    Plan.PLUS: Entitlements(Plan.PLUS, 10, 5, 5, 10, True, False, False),
    Plan.PRO: Entitlements(Plan.PRO, 250, 50, 20, 100, True, True, True),
}


def effective_plan(
    plan: str | None,
    subscription_status: str | None,
    sostagora_access: bool = False,
) -> Plan:
    """Resolve Stripe and Sostagora rights without letting one erase the other."""
    try:
        candidate = Plan((plan or "FREE").upper())
    except ValueError:
        candidate = Plan.FREE

    stripe_plan = (
        candidate
        if candidate is not Plan.FREE and subscription_status in ACTIVE_SUBSCRIPTION_STATUSES
        else Plan.FREE
    )
    if stripe_plan is Plan.PRO:
        return Plan.PRO
    if stripe_plan is Plan.PLUS or sostagora_access:
        return Plan.PLUS
    return Plan.FREE


def entitlements_for(
    plan: str | None,
    subscription_status: str | None,
    sostagora_access: bool = False,
) -> Entitlements:
    return ENTITLEMENTS[effective_plan(plan, subscription_status, sostagora_access)]
