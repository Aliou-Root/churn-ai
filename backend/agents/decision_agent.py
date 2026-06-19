"""
DecisionAgent — chooses the best retention action for each at-risk user.

Rules engine (extendable to LLM-based decision making).
"""

from typing import Any

ACTION_RULES: list[dict] = [
    # (condition_fn, action_type, priority, description)
    {
        "name":        "cancel_intent_discount",
        "condition":   lambda p: p["subscription"].get("cancel_at_period_end") and p["churn_score"] >= 0.5,
        "action_type": "discount",
        "priority":    1,
        "template":    "cancel_intent_50off",
        "description": "Offer 50% discount for 2 months to prevent cancellation",
    },
    {
        "name":        "billing_failure_nudge",
        "condition":   lambda p: p["usage_profile"].get("billing_failures", 0) >= 1,
        "action_type": "email",
        "priority":    2,
        "template":    "billing_failure_fix",
        "description": "Send payment method update email",
    },
    {
        "name":        "ghost_user_reactivation",
        "condition":   lambda p: p["usage_profile"].get("last_login_days_ago", 0) >= 30,
        "action_type": "email",
        "priority":    3,
        "template":    "reactivation_win_back",
        "description": "Send win-back email with feature highlights",
    },
    {
        "name":        "low_adoption_onboarding",
        "condition":   lambda p: p["usage_profile"].get("features_used", 10) < 3 and p["churn_score"] >= 0.35,
        "action_type": "email",
        "priority":    4,
        "template":    "feature_education",
        "description": "Send feature education + onboarding call invite",
    },
    {
        "name":        "high_risk_personal_call",
        "condition":   lambda p: p["risk_level"] == "critical",
        "action_type": "call",
        "priority":    5,
        "template":    "csm_outreach",
        "description": "Assign CSM to reach out personally within 24h",
    },
    {
        "name":        "medium_risk_upgrade_offer",
        "condition":   lambda p: p["risk_level"] == "medium",
        "action_type": "upgrade_offer",
        "priority":    6,
        "template":    "plan_upgrade_incentive",
        "description": "Offer plan upgrade with 1 month free to increase commitment",
    },
]


def decide(predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    For each prediction, select the highest-priority matching action.

    Parameters
    ----------
    predictions : output from PredictionAgent.predict()

    Returns
    -------
    list of decision dicts:
        customer_id  : str
        action_type  : str
        template     : str
        description  : str
        churn_score  : float
        risk_level   : str
        priority     : int
        payload      : dict  (merged context for ActionAgent)
    """
    decisions = []

    for pred in predictions:
        if pred["risk_level"] == "low":
            # No action needed for low risk users
            continue

        action = _select_action(pred)
        if action:
            decisions.append({
                "customer_id": pred["customer_id"],
                "action_type": action["action_type"],
                "template":    action["template"],
                "description": action["description"],
                "priority":    action["priority"],
                "churn_score": pred["churn_score"],
                "risk_level":  pred["risk_level"],
                "revenue_at_risk": pred["revenue_at_risk"],
                "top_factors": pred["top_factors"],
                "payload": {
                    "predicted_churn_date": pred["predicted_churn_date"],
                    "days_to_churn":        pred["predicted_churn_days"],
                    "usage_profile":        pred["usage_profile"],
                    "subscription":         pred["subscription"],
                },
            })

    # Sort by priority (lowest number = highest priority)
    decisions.sort(key=lambda x: (x["priority"], -x["churn_score"]))
    return decisions


def _select_action(prediction: dict) -> dict | None:
    """Return the highest-priority matching rule for this prediction."""
    matching = []
    for rule in ACTION_RULES:
        try:
            if rule["condition"](prediction):
                matching.append(rule)
        except Exception:
            pass

    if not matching:
        return None

    # Return the rule with the lowest priority number (= highest priority)
    return min(matching, key=lambda r: r["priority"])
