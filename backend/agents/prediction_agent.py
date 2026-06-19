"""
PredictionAgent — converts analysis signals into a final churn probability
score (0 → 1) and risk category, using an ML-style heuristic model.

In production: swap _predict_score() with a trained scikit-learn / XGBoost model.
"""

from datetime import datetime, timedelta
from typing import Any

import config
from agents import model

# Fallback thresholds — overridden at runtime by the values in config.current().
RISK_THRESHOLDS = {
    "low":      (0.00, 0.30),
    "medium":   (0.30, 0.55),
    "high":     (0.55, 0.75),
    "critical": (0.75, 1.01),
}


def predict(analysis_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Parameters
    ----------
    analysis_results : output from AnalysisAgent.run()

    Returns
    -------
    list of prediction dicts, sorted by score descending:
        customer_id          : str
        churn_score          : float  (0–1)
        risk_level           : "low" | "medium" | "high" | "critical"
        revenue_at_risk      : float  (€/month)
        predicted_churn_days : int    (estimated days until churn)
        top_factors          : list[str]
        usage_profile        : dict
    """
    predictions = []

    for result in analysis_results:
        score      = _predict_score(result)
        risk_level = _classify_risk(score)
        mrr        = _extract_mrr(result)
        days       = _estimate_days_to_churn(score)
        factors    = _top_factors(result["risk_signals"])

        predictions.append({
            "customer_id":          result["customer_id"],
            "churn_score":          round(score, 4),
            "risk_level":           risk_level,
            "revenue_at_risk":      round(mrr, 2),
            "predicted_churn_days": days,
            "predicted_churn_date": (
                datetime.utcnow() + timedelta(days=days)
            ).isoformat(),
            "top_factors":          factors,
            "usage_profile":        result.get("usage_profile", {}),
            "subscription":         result.get("subscription", {}),
            "predicted_at":         datetime.utcnow().isoformat(),
        })

    predictions.sort(key=lambda x: x["churn_score"], reverse=True)
    return predictions


# ─── helpers ──────────────────────────────────────────────────────────────────

def _predict_score(result: dict) -> float:
    """
    Churn probability in [0,1].

    Uses the trained scikit-learn model when available; otherwise blends the
    weighted signal score with usage-depth heuristics (deterministic fallback).
    """
    usage = result.get("usage_profile", {})
    cancel_intent = result.get("subscription", {}).get("cancel_at_period_end", False)

    ml = model.predict_proba(usage, cancel_intent)
    if ml is not None:
        # Blend the model with the rules so a hard cancel-intent signal is never
        # under-weighted by the smooth model output.
        base = result["signal_score"]
        score = 0.7 * ml + 0.3 * base
        return max(0.0, min(1.0, score))

    # ── Heuristic fallback (no scikit-learn) ──────────────────────────────────
    base = result["signal_score"]
    inactivity_days = usage.get("last_login_days_ago", 0)
    inactivity_boost = min(inactivity_days / 60, 0.20)
    features_used = usage.get("features_used", 0)
    engagement_penalty = min(features_used / 30, 0.10)
    score = base + inactivity_boost - engagement_penalty
    return max(0.0, min(1.0, score))


def _classify_risk(score: float) -> str:
    """Classify using the runtime-configurable thresholds."""
    cfg = config.current()
    if score >= cfg["threshold_critical"]:
        return "critical"
    if score >= cfg["threshold_high"]:
        return "high"
    if score >= cfg["threshold_medium"]:
        return "medium"
    return "low"


def _extract_mrr(result: dict) -> float:
    plan = result.get("subscription", {}).get("plan", {})
    amount = plan.get("amount", 0)         # Stripe stores in cents
    return amount / 100


def _estimate_days_to_churn(score: float) -> int:
    """Higher score → fewer days until estimated churn."""
    if score >= 0.80:
        return 7
    elif score >= 0.60:
        return 14
    elif score >= 0.40:
        return 30
    elif score >= 0.25:
        return 60
    return 90


def _top_factors(signals: dict[str, bool]) -> list[str]:
    active = [k for k, v in signals.items() if v]
    labels = {
        "no_login_30d":       "No login in 30+ days",
        "low_logins":         "Low login frequency",
        "low_feature_usage":  "Low feature adoption",
        "billing_failure":    "Billing failure detected",
        "support_escalation": "High support ticket volume",
        "cancel_intent":      "Cancellation intent flagged",
    }
    return [labels.get(k, k) for k in active]
