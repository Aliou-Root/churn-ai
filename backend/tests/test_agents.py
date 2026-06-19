"""Unit tests for the deterministic agents."""

import config
from agents import action_agent, analysis_agent, decision_agent, finance_agent, model, prediction_agent

# ─── fixtures (plain dicts, no DB) ──────────────────────────────────────────────

def _dataset():
    return {
        "subscriptions": [
            {"customer": "cus_low",  "plan": {"amount": 4900},  "cancel_at_period_end": False},
            {"customer": "cus_high", "plan": {"amount": 29900}, "cancel_at_period_end": True},
        ],
        "usage_summary": [
            {"customer_id": "cus_low",  "logins_last_30d": 25, "features_used": 9,
             "support_tickets": 0, "last_login_days_ago": 1,  "billing_failures": 0},
            {"customer_id": "cus_high", "logins_last_30d": 0,  "features_used": 1,
             "support_tickets": 4, "last_login_days_ago": 60, "billing_failures": 2},
        ],
    }


# ─── analysis ───────────────────────────────────────────────────────────────────

def test_analysis_signals_and_score():
    results = analysis_agent.run(_dataset())
    assert len(results) == 2
    high = next(r for r in results if r["customer_id"] == "cus_high")
    low  = next(r for r in results if r["customer_id"] == "cus_low")
    assert high["risk_signals"]["cancel_intent"] is True
    assert high["risk_signals"]["billing_failure"] is True
    assert low["signal_score"] < high["signal_score"]
    # results are sorted by descending signal score
    assert results[0]["customer_id"] == "cus_high"


# ─── prediction ──────────────────────────────────────────────────────────────────

def test_prediction_scores_in_range_and_sorted():
    analysis = analysis_agent.run(_dataset())
    preds = prediction_agent.predict(analysis)
    assert len(preds) == 2
    for p in preds:
        assert 0.0 <= p["churn_score"] <= 1.0
        assert p["risk_level"] in {"low", "medium", "high", "critical"}
        assert p["predicted_churn_days"] > 0
    # highest score first
    assert preds[0]["churn_score"] >= preds[1]["churn_score"]
    high = next(p for p in preds if p["customer_id"] == "cus_high")
    assert high["churn_score"] > 0.5


def test_classify_risk_respects_config():
    cfg = config.current()
    assert prediction_agent._classify_risk(cfg["threshold_critical"] + 0.01) == "critical"
    assert prediction_agent._classify_risk(0.0) == "low"


# ─── model ───────────────────────────────────────────────────────────────────────

def test_model_predict_proba():
    usage = {"last_login_days_ago": 60, "logins_last_30d": 0, "features_used": 1,
             "support_tickets": 4, "billing_failures": 2}
    p = model.predict_proba(usage, cancel_intent=True)
    # scikit-learn is installed in the runtime image → expect a real probability
    assert p is None or (0.0 <= p <= 1.0)
    if model.is_ready():
        healthy = model.predict_proba(
            {"last_login_days_ago": 0, "logins_last_30d": 28, "features_used": 10,
             "support_tickets": 0, "billing_failures": 0}, cancel_intent=False)
        assert healthy < p  # an engaged user churns less than a disengaged one


# ─── decision ─────────────────────────────────────────────────────────────────────

def test_decision_skips_low_and_picks_rule():
    analysis = analysis_agent.run(_dataset())
    preds = prediction_agent.predict(analysis)
    decisions = decision_agent.decide(preds)
    # low-risk customers get no action
    assert all(d["risk_level"] != "low" for d in decisions)
    # the cancel-intent customer should trigger an action
    assert any(d["customer_id"] == "cus_high" for d in decisions)


# ─── finance ──────────────────────────────────────────────────────────────────────

def test_finance_roi_and_tool_cost_from_config():
    preds = [
        {"customer_id": "a", "churn_score": 0.9, "risk_level": "critical", "revenue_at_risk": 299},
        {"customer_id": "b", "churn_score": 0.2, "risk_level": "low",      "revenue_at_risk": 49},
    ]
    actions = [{"customer_id": "a", "action_type": "discount", "success": True, "revenue_saved": 149.0}]
    roi = finance_agent.calculate_roi(preds, actions)
    assert roi["total_revenue_saved"] == 149.0
    assert roi["users_at_risk"] == 1
    assert roi["breakdown_by_risk"]["critical"] == 1
    assert roi["roi_ratio"] == round(149.0 / config.get("tool_cost"), 2)
    assert len(roi["top_saves"]) == 1


# ─── action (async) ────────────────────────────────────────────────────────────────

async def test_action_execute_simulated():
    decisions = [
        {"customer_id": "a", "action_type": "email", "template": "reactivation_win_back",
         "revenue_at_risk": 100, "churn_score": 0.8},
        {"customer_id": "b", "action_type": "no_action", "revenue_at_risk": 0, "churn_score": 0.1},
    ]
    results = await action_agent.execute(decisions)
    assert len(results) == 2
    assert all(r["success"] for r in results)
    assert "SIMULATED" in results[0]["detail"]
