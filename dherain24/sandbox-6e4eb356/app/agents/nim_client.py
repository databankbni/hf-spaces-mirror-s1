import json
import logging
import httpx
from typing import Optional
from app.core.config import settings
from app.agents.schemas import AgentProposal, CaseContextPackage
from app.agents.prompt_builder import build_nim_prompt, synthesize_error_code

logger = logging.getLogger(__name__)

def generate_heuristic_proposal(context: CaseContextPackage) -> AgentProposal:
    """Deterministic fallback strategy grounded in payment recovery rules."""
    semantic_reason, _ = synthesize_error_code(context.raw_decline_code or "", context.failure_reason)

    # 1. High value threshold -> Escalate
    if context.amount_at_risk >= 100000.0:
        return AgentProposal(
            action_type="escalate_human",
            expected_recovery_probability=0.85,
            expected_recovered_value=context.amount_at_risk * 0.85,
            customer_friction="low",
            plain_english_rationale=f"High-value case (₹{context.amount_at_risk:,.2f}) requires human supervisor review per merchant safety policy.",
            why_not_alternatives="Automated retries carry chargeback or balance risks at this transaction size.",
            requires_human_approval=True,
        )

    # 2. Too many prior retries or low tenure with low success -> No Action
    if context.prior_actions_count >= context.merchant_max_retries or (context.customer_tenure_days < 30 and context.historical_success_rate < 0.3):
        return AgentProposal(
            action_type="no_action",
            expected_recovery_probability=0.04,
            expected_recovered_value=0.0,
            customer_friction="high",
            plain_english_rationale="Retry budget exhausted or low customer recovery likelihood. Deliberately withholding action to avoid merchant customer fatigue and gateway costs.",
            why_not_alternatives="Further retries or generic notifications have a historical success rate <5%.",
            requires_human_approval=False,
        )

    # 3. Card expired / invalid instrument -> Payment Link
    if "expired" in semantic_reason or "invalid" in semantic_reason:
        prob = 0.42
        return AgentProposal(
            action_type="payment_link",
            expected_recovery_probability=prob,
            expected_recovered_value=round(context.amount_at_risk * prob - 50.0, 2),
            customer_friction="low",
            plain_english_rationale="Payment instrument is expired or invalid. Retrying the same instrument will fail. Dispatching a secure Razorpay Payment Link allows customer to update payment method.",
            why_not_alternatives="Immediate or delayed retry on an expired card is mathematically 0% effective.",
            requires_human_approval=False,
        )

    # 4. Insufficient funds or temporary decline -> Delayed Retry
    prob = 0.32 if context.historical_success_rate > 0.7 else 0.20
    delay = 36.0
    return AgentProposal(
        action_type="delayed_retry",
        delay_hours=delay,
        expected_recovery_probability=prob,
        expected_recovered_value=round(context.amount_at_risk * prob, 2),
        customer_friction="low",
        plain_english_rationale=f"Temporary balance or network decline. Customer has a {context.historical_success_rate * 100:.0f}% historical success rate. Delaying retry by {delay:.0f}h maximizes recovery probability without customer friction.",
        why_not_alternatives="Immediate retry typically encounters the same balance deficit; payment link creates unnecessary customer friction.",
        requires_human_approval=False,
    )

class NimClient:
    def __init__(self):
        self.api_key = settings.NVIDIA_API_KEY
        self.base_url = settings.NIM_BASE_URL.rstrip("/")
        self.primary_model = settings.PRIMARY_MODEL
        self.fast_model = settings.FAST_MODEL

    async def get_recovery_decision(self, context: CaseContextPackage) -> AgentProposal:
        # If no API key configured, use deterministic rule fallback immediately
        if not self.api_key or "nvapi" not in self.api_key:
            logger.info("Using deterministic fallback agent (NVIDIA_API_KEY not configured).")
            return generate_heuristic_proposal(context)

        messages = build_nim_prompt(context)
        model = self.primary_model if context.amount_at_risk > 20000.0 else self.fast_model

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 800,
            "response_format": {"type": "json_object"},
        }

        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )

                if response.status_code == 200:
                    res_json = response.json()
                    content = res_json["choices"][0]["message"]["content"]
                    parsed = json.loads(content)
                    return AgentProposal(**parsed)
                else:
                    logger.warning(
                        f"NVIDIA NIM API returned status {response.status_code}: {response.text}. Using fallback proposal."
                    )
                    return generate_heuristic_proposal(context)
        except Exception as e:
            logger.warning(f"Error connecting to NVIDIA NIM ({e}). Falling back to deterministic proposal.")
            return generate_heuristic_proposal(context)

nim_client = NimClient()
