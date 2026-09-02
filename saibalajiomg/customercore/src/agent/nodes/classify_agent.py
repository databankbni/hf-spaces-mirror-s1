import mlflow
import os
import structlog
from typing import List
from src.agent.state import AgentState

log = structlog.get_logger()

CATEGORY_MODEL = "customercore-category-classifier"
PRIORITY_MODEL = "customercore-priority-classifier"

CATEGORIES = [
    "bug", "feature_request", "security", "performance",
    "billing", "auth", "docs", "question", "incident", "other"
]
PRIORITIES = ["low", "medium", "high", "critical"]

def _load_model(name: str):
    """Attempt to load classifier model from MLflow tracking server."""
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

def heuristic_classify(body: str) -> tuple[str, str]:
    """
    Fallback high-quality heuristic classification for categories and priorities.
    Matches industry support ticket routing logic.
    """
    text = body.lower()
    
    # ── Category Heuristics ────────────────────────────────────────────────────
    category = "other"
    
    if any(kw in text for kw in ["hacked", "leak", "unauthorized", "vulnerability", "breach", "cve", "compromised", "exploit", "security", "sicherheit", "fuite", "breche", "brecha", "exposed", "exposé", "expuesto", "divulgada", "divulgado"]):
        category = "security"
    elif any(kw in text for kw in ["outage", "offline", "completely down", "service unavailable", "is down", "not accessible", "500 error", "ausfall", "hors service", "panne", "caído", "caido"]):
        category = "incident"
    elif any(kw in text for kw in ["login", "password", "oauth", "token", "signin", "sign-in", "signup", "mfa", "2fa", "authentication", "einloggen", "passwort", "passworts", "mot de passe", "connexion", "contraseña", "iniciar sesión", "senha", "entrar", "konto gesperrt", "gesperrt"]):
        category = "auth"
    elif any(kw in text for kw in ["billing", "payment", "charge", "refund", "invoice", "stripe", "checkout", "cost", "pay", "rechnung", "zahlung", "facture", "paiement", "factura", "pago"]):
        category = "billing"
    elif any(kw in text for kw in ["slow", "latency", "lag", "timeout", "degraded", "delay", "performance", "high cpu"]):
        category = "performance"
    elif any(kw in text for kw in ["docs", "documentation", "how to", "guide", "tutorial", "where can i find"]):
        category = "docs"
    elif any(kw in text for kw in ["feature request", "would be nice", "can we add", "suggest", "improve", "request feature"]):
        category = "feature_request"
    elif any(kw in text for kw in ["bug", "error", "fail", "broken", "issue", "crash", "wrong", "incorrect", "exception"]):
        category = "bug"
    elif "?" in text:
        category = "question"
        
    # ── Priority Heuristics ────────────────────────────────────────────────────
    priority = "medium"
    
    # Critical criteria
    if category in ["security", "incident"] or any(kw in text for kw in ["completely down", "production down", "outage", "all users affected"]):
        priority = "critical"
    # High criteria
    elif any(kw in text for kw in ["urgent", "blocking", "failed", "broken", "asap", "invoice issue", "payment failed", "error", "dringend", "gesperrt", "fehlgeschlagen", "kaputt", "bloqué", "bloque", "urgente", "bloqueado", "bloqueada"]):
        priority = "high"
    # Low criteria
    elif category in ["docs", "feature_request"] or any(kw in text for kw in ["minor", "typo", "cosmetic", "wont fix"]):
        priority = "low"
        
    return category, priority

def classify_agent_node(state: AgentState) -> AgentState:
    ticket = state["ticket"]
    body = ticket["body"]
    
    # 1. Try MLflow ML models first
    category = None
    priority = None
    models_used: List[str] = state.get("models_used") or []
    
    try:
        # Check if feature engineering module exists
        from src.ml.feature_engineering import create_structured_features
        import pandas as pd
        
        df = pd.DataFrame([{
            "body": body,
            "priority": "medium",
            "customer_tier": ticket.get("customer_tier", "professional"),
            "reopen_count": 0,
            "ticket_age_hours": 24,
        }])
        features = create_structured_features(df)
        
        # Predict Category
        cat_model = _load_model(CATEGORY_MODEL)
        if cat_model:
            cat_idx = cat_model.predict(features)[0]
            category = CATEGORIES[int(cat_idx) % len(CATEGORIES)]
            models_used.append(CATEGORY_MODEL)
            
        # Predict Priority
        pri_model = _load_model(PRIORITY_MODEL)
        if pri_model:
            pri_idx = pri_model.predict(features)[0]
            priority = PRIORITIES[int(pri_idx) % len(PRIORITIES)]
            models_used.append(PRIORITY_MODEL)
            
    except (ImportError, ModuleNotFoundError) as e:
        log.debug("ml_modules_missing_using_heuristics", error=str(e))
    except Exception as e:
        log.warning("ml_prediction_failed_using_heuristics", error=str(e))
        
    # 2. Fall back to high-quality heuristics if ML prediction failed or models not found
    if not category or not priority:
        h_cat, h_pri = heuristic_classify(body)
        category = category or h_cat
        priority = priority or h_pri
        models_used.append("heuristic-classifier-v1.0")
        
    # 3. Apply customer tier multiplier: VIP customer gets upgraded priority
    tier = ticket.get("customer_tier", "free").lower()
    if tier == "enterprise":
        if priority == "low":
            priority = "medium"
        elif priority == "medium":
            priority = "high"
        elif priority == "high":
            priority = "critical"
            
    log.info("classify_agent_done", category=category, priority=priority, models_used=models_used)
    
    return {
        "category": category,
        "priority": priority,
        "current_step": "classify_agent",
        "models_used": models_used,
    }
