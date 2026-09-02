from typing import Dict, Any, Tuple
from app.agents.schemas import CaseContextPackage

# Map raw gateway and bank error strings to semantic failure intelligence
RAW_CODE_TAXONOMY: Dict[str, Tuple[str, str]] = {
    "NPCI_U19": ("insufficient_funds", "Customer account lacked required balance at moment of attempt."),
    "ERR_BANK_AUTH_502": ("temporary_network_decline", "Issuing bank authorization server experienced temporary gateway timeout."),
    "CARD_EXPIRED": ("expired_payment_method", "Instrument expired or deactivated. Recurring charge impossible without update."),
    "INVALID_CARD_DETAILS": ("invalid_instrument", "Card number or CVV rejected by network."),
    "LIMIT_EXCEEDED": ("customer_limit_reached", "Daily or per-transaction UPI/card limit exceeded."),
    "MANDATE_REVOKED": ("mandate_cancelled", "Customer or bank cancelled the recurring mandate."),
    "PAYMENT_STOPPED": ("user_cancelled", "Payment explicitly declined or cancelled during 2FA challenge."),
}

def synthesize_error_code(raw_code: str, fallback_reason: str) -> Tuple[str, str]:
    if not raw_code:
        return fallback_reason, "Standard payment failure reported by gateway."
    
    clean_code = raw_code.strip().upper()
    for key, (semantic, explanation) in RAW_CODE_TAXONOMY.items():
        if key in clean_code:
            return semantic, explanation
            
    return fallback_reason, f"Gateway reported: {raw_code}"

SYSTEM_PROMPT = """You are the Revenue Recovery Intelligence (RRI) Agent for Razorpay merchants.
Your mission is to maximize recovered revenue while minimizing unnecessary customer friction and respecting merchant guardrails.

CRITICAL RULES:
1. You are a DECISION ENGINE, not a chatbot.
2. Select strictly ONE recommended action from:
   - delayed_retry: Customer has temporary failure (e.g. insufficient funds, network blip) and historical pattern suggests recovery after a specific delay (e.g. 24-48 hours).
   - payment_link: Payment instrument is unusable (expired, invalid), so an alternate payment link must be generated.
   - escalate_human: High-value transaction or ambiguous dispute requiring merchant operational review.
   - no_action: The recovery probability is too low, customer has repeated failures, or intervention cost/friction exceeds expected value. DO NOT spam customers!
3. Expected Recovered Value = (Expected Probability * Amount At Risk) - Customer Friction Penalty.
4. Output MUST be valid JSON adhering strictly to the provided schema.
"""

def build_nim_prompt(context: CaseContextPackage) -> list:
    semantic_reason, error_explanation = synthesize_error_code(
        context.raw_decline_code or "", context.failure_reason
    )

    user_message = f"""Case Investigation Context:
- Case ID: {context.case_id}
- Revenue At Risk: ₹{context.amount_at_risk:,.2f} ({context.currency})
- Reported Failure Reason: {context.failure_reason}
- Raw Gateway Code: {context.raw_decline_code or 'None'}
- Technical Error Synthesis: {semantic_reason} ({error_explanation})
- Customer Tenure: {context.customer_tenure_days} days
- Customer Historical Success Rate: {context.historical_success_rate * 100:.1f}%
- Prior Intervention Attempts: {context.prior_actions_count} / {context.merchant_max_retries} allowed

Historical Case Precedents:
{context.similar_cases_summary if context.similar_cases_summary else 'No exact merchant precedents available.'}

Analyze the customer and failure dynamics. Decide the next best action and return the structured JSON decision.
"""

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]
