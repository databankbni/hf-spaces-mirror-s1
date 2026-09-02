import os
import mlflow
import structlog
from typing import List
from src.agent.state import AgentState

log = structlog.get_logger()

CHURN_MODEL = "customercore-churn-classifier"
SLA_MODEL = "customercore-sla-classifier"

def _load_model(name: str):
    """Attempt to load risk model from MLflow tracking server."""
    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", "sqlite:///mlruns.db")
    mlflow.set_tracking_uri(tracking_uri)
    client = mlflow.MlflowClient()
    try:
        versions = client.get_latest_versions(name, stages=["Production", "None"])
        if versions:
            return mlflow.sklearn.load_model(f"models:/{name}/{versions[0].version}")
    except Exception as e:
        log.warning("model_load_failed", name=name, error=str(e))
    return None

def calculate_heuristic_risks(body: str, category: str, priority: str, tier: str) -> tuple[float, float]:
    """
    High-fidelity heuristic calculation of churn risk and SLA breach risk.
    Balances customer tier, priority severity, category, and specific text sentiment cues.
    """
    text = body.lower()
    
    # ── SLA Breach Risk Calculation ────────────────────────────────────────────
    # Baseline by priority
    sla_base = {
        "low": 0.10,
        "medium": 0.25,
        "high": 0.55,
        "critical": 0.85
    }
    sla_risk = sla_base.get(priority, 0.25)
    
    # Enterprise or high-tier SLAs have tighter response windows, increasing breach probability
    if tier.lower() == "enterprise":
        sla_risk += 0.10
    elif tier.lower() == "professional":
        sla_risk += 0.05
        
    # High-pressure categories have tighter operation windows
    if category in ["incident", "security"]:
        sla_risk += 0.10
    elif category == "performance":
        sla_risk += 0.05
        
    # SLA risk bounds
    sla_risk = max(0.0, min(1.0, round(sla_risk, 3)))
    
    # ── Churn Risk Calculation ─────────────────────────────────────────────────
    churn_risk = 0.10  # Baseline churn risk
    
    # Priority additions
    if priority == "critical":
        churn_risk += 0.15
    elif priority == "high":
        churn_risk += 0.08
        
    # Category impact
    if category == "billing":
        churn_risk += 0.25  # Billing/double charging is the #1 churn driver
    elif category == "incident":
        churn_risk += 0.15  # Total service outages damage brand trust
    elif category == "performance":
        churn_risk += 0.08  # Persistent sluggishness leads to frustration
    elif category == "security":
        churn_risk += 0.20  # Security breaches are severe churn drivers
        
    # Tier impact (free users churn easily; enterprise accounts are highly valued, high-risk churn)
    if tier.lower() == "free":
        churn_risk += 0.10  # Low switching barriers
    elif tier.lower() == "enterprise":
        # While contractual barriers exist, a severe issue raises the "Account-at-Risk" flag
        churn_risk += 0.05
        
    # Content-based threat indicators (direct expressions of churning intent)
    churn_keywords = [
        "cancel", "refund", "close my account", "switching to", "competitor",
        "leave", "stop subscription", "unacceptable", "disappointed",
        "useless", "moving away", "sue", "legal action"
    ]
    if any(kw in text for kw in churn_keywords):
        churn_risk += 0.25
        
    # Churn risk bounds
    churn_risk = max(0.0, min(1.0, round(churn_risk, 3)))
    
    return sla_risk, churn_risk

def churn_agent_node(state: AgentState) -> AgentState:
    ticket = state["ticket"]
    body = ticket["body"]
    category = state.get("category", "other")
    priority = state.get("priority", "medium")
    tier = ticket.get("customer_tier", "free")
    
    models_used: List[str] = state.get("models_used") or []
    sla_breach_risk = None
    churn_risk = None
    
    # 1. Try MLflow ML models first
    try:
        from src.ml.feature_engineering import create_structured_features
        import pandas as pd
        
        df = pd.DataFrame([{
            "body": body,
            "priority": priority,
            "customer_tier": tier,
            "reopen_count": 0,
            "ticket_age_hours": 24,
        }])
        features = create_structured_features(df)
        
        # Predict Churn Risk
        churn_model = _load_model(CHURN_MODEL)
        if churn_model:
            # Assume probability prediction is available
            if hasattr(churn_model, "predict_proba"):
                churn_risk = float(churn_model.predict_proba(features)[0][1])
            else:
                churn_risk = float(churn_model.predict(features)[0])
            models_used.append(CHURN_MODEL)
            
        # Predict SLA Risk
        sla_model = _load_model(SLA_MODEL)
        if sla_model:
            if hasattr(sla_model, "predict_proba"):
                sla_breach_risk = float(sla_model.predict_proba(features)[0][1])
            else:
                sla_breach_risk = float(sla_model.predict(features)[0])
            models_used.append(SLA_MODEL)
            
    except (ImportError, ModuleNotFoundError) as e:
        log.debug("ml_modules_missing_using_heuristics", error=str(e))
    except Exception as e:
        log.warning("ml_risk_prediction_failed_using_heuristics", error=str(e))
        
    # 2. Fall back to high-quality heuristics if ML prediction failed or models not found
    if sla_breach_risk is None or churn_risk is None:
        h_sla, h_churn = calculate_heuristic_risks(body, category, priority, tier)
        sla_breach_risk = sla_breach_risk if sla_breach_risk is not None else h_sla
        churn_risk = churn_risk if churn_risk is not None else h_churn
        models_used.append("heuristic-risk-engine-v1.0")
        
    log.info("churn_agent_done", sla_breach_risk=sla_breach_risk, churn_risk=churn_risk, models_used=models_used)
    
    return {
        "sla_breach_risk": sla_breach_risk,
        "churn_risk": churn_risk,
        "current_step": "churn_agent",
        "models_used": models_used,
    }
