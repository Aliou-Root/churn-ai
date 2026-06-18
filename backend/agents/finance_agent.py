"""
FinanceAgent — calculates ROI, revenue saved, and business impact metrics.
"""

from typing import Any
from datetime import datetime


def calculate_roi(
    predictions: list[dict[str, Any]],
    action_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Aggregate financial impact of the pipeline run.

    Returns
    -------
    dict:
        total_revenue_at_risk   : float  (€/month)
        total_revenue_saved     : float  (estimated €/month recovered)
        actions_executed        : int
        actions_succeeded       : int
        success_rate            : float  (%)
        avg_churn_score         : float
        users_at_risk           : int
        roi_ratio               : float  (revenue_saved / tool_cost)
        breakdown_by_risk       : dict
        top_saves               : list
        calculated_at           : str
    """
    total_at_risk  = sum(p.get("revenue_at_risk", 0) for p in predictions)
    total_saved    = sum(a.get("revenue_saved", 0) for a in action_results if a.get("success"))
    succeeded      = sum(1 for a in action_results if a.get("success"))
    total_actions  = len(action_results)

    avg_score = (
        sum(p.get("churn_score", 0) for p in predictions) / len(predictions)
        if predictions else 0
    )

    breakdown = _breakdown_by_risk(predictions)
    top_saves = _top_saves(action_results, predictions)

    # Assume tool costs 149€/month for this example
    tool_cost = 149.0
    roi_ratio = round(total_saved / tool_cost, 2) if tool_cost > 0 else 0

    return {
        "total_revenue_at_risk": round(total_at_risk, 2),
        "total_revenue_saved":   round(total_saved, 2),
        "actions_executed":      total_actions,
        "actions_succeeded":     succeeded,
        "success_rate":          round((succeeded / total_actions * 100) if total_actions else 0, 1),
        "avg_churn_score":       round(avg_score, 3),
        "users_at_risk":         len([p for p in predictions if p.get("risk_level") != "low"]),
        "roi_ratio":             roi_ratio,
        "breakdown_by_risk":     breakdown,
        "top_saves":             top_saves,
        "calculated_at":         datetime.utcnow().isoformat(),
    }


def _breakdown_by_risk(predictions: list[dict]) -> dict:
    breakdown = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    for p in predictions:
        level = p.get("risk_level", "low")
        breakdown[level] = breakdown.get(level, 0) + 1
    return breakdown


def _top_saves(
    action_results: list[dict],
    predictions: list[dict],
) -> list[dict]:
    pred_map = {p["customer_id"]: p for p in predictions}
    saves = []
    for action in action_results:
        if action.get("success") and action.get("revenue_saved", 0) > 0:
            cid  = action["customer_id"]
            pred = pred_map.get(cid, {})
            saves.append({
                "customer_id":   cid,
                "action_type":   action["action_type"],
                "revenue_saved": action["revenue_saved"],
                "churn_score":   pred.get("churn_score", 0),
                "risk_level":    pred.get("risk_level", "unknown"),
            })
    saves.sort(key=lambda x: x["revenue_saved"], reverse=True)
    return saves[:5]
