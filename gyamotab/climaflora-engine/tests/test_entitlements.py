from app.services.entitlements import Plan, effective_plan, entitlements_for


def test_paid_plan_requires_active_subscription():
    assert effective_plan("PLUS", None) is Plan.FREE
    assert effective_plan("PRO", "past_due") is Plan.FREE
    assert effective_plan("PRO", "canceled") is Plan.FREE


def test_active_and_trialing_unlock_paid_plan():
    assert effective_plan("PLUS", "active") is Plan.PLUS
    assert effective_plan("PRO", "trialing") is Plan.PRO


def test_unknown_plan_fails_closed():
    assert effective_plan("ADMIN", "active") is Plan.FREE
    assert effective_plan(None, "active") is Plan.FREE


def test_sostagora_grants_plus_without_a_stripe_subscription():
    assert effective_plan("FREE", None, sostagora_access=True) is Plan.PLUS
    assert effective_plan("PRO", "canceled", sostagora_access=True) is Plan.PLUS
    assert effective_plan("PRO", "active", sostagora_access=True) is Plan.PRO


def test_matrix_keeps_free_search_useful():
    free = entitlements_for("FREE", None)
    assert free.saved_projects == 1
    assert free.saved_sites == 1
    assert free.commercial_use is False


def test_plus_project_limit_matches_public_offer():
    plus = entitlements_for("PLUS", "active")
    assert plus.saved_projects == 10
    assert plus.saved_sites == 5
