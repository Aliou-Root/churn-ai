"""
AnalysisAgent — detects churn patterns from collected data.

Output: risk signals per user (login decline, feature abandonment, etc.)
"""

from datetime import datetime
from typing import Any

# Risk signal weights
WEIGHTS = {
    "no_login_30d":       0.30,
    "low_feature_usage":  0.20,
    "billing_failure":    0.25,
    "support_escalation": 0.10,
    "cancel_intent":      0.35,
    "low_logins":         0.15,
}


def run(dataset: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Analyse collected dataset and return per-user risk signals.

    Parameters
    ----------
    dataset : output from DataAgent.collect()

    Returns
    -------
    list of dicts, one per customer:
        customer_id     : str
        risk_signals    : dict[signal_name → bool]
        signal_score    : float  (weighted sum, 0–1)
        usage_profile   : dict
    """
    subscriptions  = {s["customer"]: s for s in dataset["subscriptions"]}
    usage_by_cid   = {u["customer_id"]: u for u in dataset["usage_summary"]}

    results = []

    for cid, usage in usage_by_cid.items():
        sub  = subscriptions.get(cid, {})
        signals = _compute_signals(usage, sub)
        score   = _weighted_score(signals)

        results.append({
            "customer_id":   cid,
            "risk_signals":  signals,
            "signal_score":  round(score, 4),
            "usage_profile": usage,
            "subscription":  sub,
            "analyzed_at":   datetime.utcnow().isoformat(),
        })

    # Sort by highest risk first
    results.sort(key=lambda x: x["signal_score"], reverse=True)
    return results


# ─── helpers ──────────────────────────────────────────────────────────────────

def _compute_signals(usage: dict, sub: dict) -> dict[str, bool]:
    return {
        "no_login_30d":       usage.get("last_login_days_ago", 0) >= 30,
        "low_logins":         usage.get("logins_last_30d", 0) < 5,
        "low_feature_usage":  usage.get("features_used", 10) < 3,
        "billing_failure":    usage.get("billing_failures", 0) >= 1,
        "support_escalation": usage.get("support_tickets", 0) >= 3,
        "cancel_intent":      sub.get("cancel_at_period_end", False),
    }


def _weighted_score(signals: dict[str, bool]) -> float:
    total_weight = sum(WEIGHTS.values())
    raw = sum(WEIGHTS[k] * int(v) for k, v in signals.items() if k in WEIGHTS)
    return min(raw / total_weight, 1.0)
