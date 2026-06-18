"""
AICEOAgent v4 — orchestrateur principal.

Améliorations v4 :
  - customer_lookup depuis la DB (nom, company, tenure réels)
  - WEEKLY_ANALYST_SYSTEM_PROMPT exposé pour scheduler.py
  - _call_claude_sync / _parse_json exposés pour scheduler.py
  - Graceful degradation complète si Claude non configuré
"""

import os
import json
import asyncio
import logging
from datetime import datetime
from typing import Any

import anthropic

from agents import data_agent, analysis_agent, prediction_agent
from agents import decision_agent, action_agent, finance_agent

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic | None:
    global _client
    if not ANTHROPIC_API_KEY:
        return None
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


# ─── System Prompts ───────────────────────────────────────────────────────────

CEO_SYSTEM_PROMPT = """You are the Chief Strategy Officer of a SaaS churn prevention system called ChurnAI.

Your role is to receive the complete output of a deterministic churn analysis pipeline and add the reasoning layer that rules cannot provide.

## YOUR THREE TASKS

### TASK 1 — EDGE CASE RESOLUTION
For customers with churn_score between 0.38 and 0.68, reason about whether the assigned action is appropriate given the FULL context of their profile.

### TASK 2 — SYSTEMIC PATTERN DETECTION
Analyze ALL customers collectively. Only report patterns affecting 3+ customers. Do not invent patterns.

### TASK 3 — EXECUTIVE SUMMARY
Crisp summary for a SaaS founder/CEO. Max 200 words. No fluff.

## OUTPUT — raw JSON only, no preamble, no markdown fences
{
  "edge_case_overrides": [
    {"customer_id": "string", "original_action": "string", "recommended_action": "email|discount|call|upgrade_offer|no_action|flag_for_review", "reasoning": "string max 80 words", "confidence": 0.0_to_1.0}
  ],
  "systemic_patterns": [
    {"pattern_name": "string", "affected_customer_ids": ["string"], "severity": "low|medium|high|critical", "description": "string max 60 words", "hypothesis": "string max 40 words", "recommended_product_action": "string"}
  ],
  "executive_summary": {
    "health_score": 0_to_100,
    "top_risks": ["string", "string", "string"],
    "immediate_priority": "string max 30 words",
    "product_team_flag": "string max 40 words"
  }
}

## CONSTRAINTS
- Never invent customer_ids not in the input
- edge_case_overrides only for churn_score 0.38–0.68
- systemic_patterns only if 3+ customers share the pattern
- Output raw JSON only"""


COMMS_SYSTEM_PROMPT = """You are the Retention Communication Specialist for a SaaS company. Write retention messages that feel personal and human.

## INPUT
{"action_type": "email|call_script", "template_category": "billing_failure|win_back|feature_education|cancel_intent|csm_outreach|upgrade_offer", "customer": {"name": "string", "company": "string", "plan": "starter|pro|business", "mrr": float, "features_used": int, "last_login_days_ago": int, "support_tickets_last_30d": int, "billing_failures": int, "churn_score": float, "top_factors": ["string"], "days_as_customer": int, "product_name": "string"}}

## OUTPUT — raw JSON only
{"subject": "string <58 chars", "body": "string 80-140 words plain text", "tone": "urgent|warm|professional|empathetic", "personalization_applied": ["string"], "primary_cta": "string", "csm_briefing": "string or null"}

## PERSONALIZATION RULES
1. last_login_days_ago > 45 → Acknowledge gap, no guilt
2. last_login_days_ago > 90 → Lead with what changed since last login
3. mrr > 150 → Professional, no emojis
4. mrr < 60 → Peer-to-peer, first name only
5. support_tickets >= 3 → Empathy first, offer second
6. billing_failures >= 2 → "issue processing payment", not accusatory
7. features_used <= 2 → ONE feature only, no lists
8. cancel_intent + churn_score > 0.75 → Offer in line 1
9. days_as_customer > 365 → Acknowledge relationship
10. days_as_customer < 60 → Onboarding tone

## PROHIBITIONS
- Never: "hope this email finds you well", "circle back", "touch base"
- Never mention: "churn", "at-risk", "flagged"
- No HTML — plain text only
- Output raw JSON only"""


WEEKLY_ANALYST_SYSTEM_PROMPT = """You are a churn data analyst for a SaaS company. Receive one week of aggregated churn data and produce a strategic weekly report.

## INPUT
{"week_start": "ISO", "week_end": "ISO", "total_customers_monitored": int, "plan_distribution": {...}, "risk_breakdown": {...}, "total_revenue_at_risk": float, "total_revenue_saved": float, "actions_taken": int, "actions_succeeded": int}

## OUTPUT — raw JSON only
{"week_summary": {"overall_health": "improving|stable|declining", "health_score_change": float, "total_at_risk": int, "revenue_at_risk_eur": float, "revenue_recovered_eur": float, "net_revenue_impact_eur": float}, "top_churn_drivers": [{"driver": "string", "affected_count": int, "trend": "increasing|stable|decreasing", "recommended_fix": "string"}], "segment_analysis": {"most_at_risk_plan": "starter|pro|business", "healthiest_segment": "string", "insight": "string"}, "action_effectiveness": {"best_performing_action": "string", "worst_performing_action": "string", "recommendation": "string"}, "founder_alert": "string or null"}

## CONSTRAINTS
- Only report trends with 3+ data points. Do not fabricate. Output raw JSON only."""


# ─── Claude helpers ───────────────────────────────────────────────────────────

def _call_claude_sync(system: str, user_content: str, max_tokens: int = 2000) -> str:
    """Appel synchrone — à exécuter via asyncio.to_thread()."""
    client = _get_client()
    if not client:
        return ""
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_content}],
        )
        return response.content[0].text if response.content else ""
    except Exception as exc:
        logger.warning("Claude API call failed: %s", exc)
        return ""


def _parse_json(raw: str) -> dict | None:
    """Strip fences Markdown éventuels et parse JSON."""
    if not raw:
        return None
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        parts   = cleaned.split("```")
        cleaned = parts[2] if len(parts) > 2 else parts[-1]
        cleaned = cleaned.lstrip("json").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("Claude JSON parse failed: %s…", raw[:150])
        return None


# ─── CEO Agent ────────────────────────────────────────────────────────────────

def _should_call_ceo(predictions: list, decisions: list) -> bool:
    if not ANTHROPIC_API_KEY:
        return False
    edge_cases = sum(1 for p in predictions if 0.38 <= p["churn_score"] <= 0.68)
    at_risk    = sum(1 for p in predictions if p["risk_level"] != "low")
    return edge_cases >= 1 or at_risk >= 3


async def _call_ceo_agent(predictions: list, decisions: list, roi: dict) -> dict:
    empty = {"edge_case_overrides": [], "systemic_patterns": [], "executive_summary": {}}
    if not _should_call_ceo(predictions, decisions):
        logger.info("CEO agent skipped")
        return empty

    payload = json.dumps({"predictions": predictions, "decisions": decisions, "roi": roi})
    logger.info("CEO Agent appelé (%d prédictions)…", len(predictions))
    raw    = await asyncio.to_thread(_call_claude_sync, CEO_SYSTEM_PROMPT, payload, 2000)
    result = _parse_json(raw)
    if not isinstance(result, dict):
        logger.warning("CEO agent: réponse invalide, fallback")
        return empty
    logger.info("CEO agent: %d overrides, %d patterns",
                len(result.get("edge_case_overrides", [])),
                len(result.get("systemic_patterns", [])))
    return result


def _apply_ceo_overrides(decisions: list, ceo_insights: dict) -> list:
    overrides = {
        o["customer_id"]: o
        for o in ceo_insights.get("edge_case_overrides", [])
        if o.get("confidence", 0) > 0.70
    }
    if not overrides:
        return decisions
    updated = []
    for d in decisions:
        cid = d["customer_id"]
        if cid in overrides:
            o = overrides[cid]
            d = dict(d)
            d["action_type"]  = o["recommended_action"]
            d["ceo_override"] = {"original_action": o["original_action"],
                                 "reasoning": o["reasoning"],
                                 "confidence": o["confidence"]}
            logger.info("CEO override %s: %s → %s", cid, o["original_action"], d["action_type"])
        updated.append(d)
    return updated


# ─── Communication Agent ──────────────────────────────────────────────────────

def _build_comms_payload(decision: dict, prediction: dict,
                         customer_lookup: dict | None = None) -> str:
    usage  = prediction.get("usage_profile", {})
    sub    = prediction.get("subscription", {})
    mrr    = sub.get("plan", {}).get("amount", 0) / 100
    cid    = decision["customer_id"]

    plan_name = "starter"
    if mrr >= 249: plan_name = "business"
    elif mrr >= 99: plan_name = "pro"

    lookup      = (customer_lookup or {}).get(cid, {})
    name        = lookup.get("name", cid)
    company     = lookup.get("company", "")
    days_tenure = lookup.get("days_as_customer", 180)

    return json.dumps({
        "action_type":       decision["action_type"],
        "template_category": decision.get("template", "win_back"),
        "customer": {
            "name": name, "company": company, "plan": plan_name,
            "mrr": round(mrr, 2),
            "features_used":           usage.get("features_used", 5),
            "last_login_days_ago":     usage.get("last_login_days_ago", 0),
            "support_tickets_last_30d":usage.get("support_tickets", 0),
            "billing_failures":        usage.get("billing_failures", 0),
            "churn_score":             prediction.get("churn_score", 0.5),
            "top_factors":             prediction.get("top_factors", []),
            "days_as_customer":        days_tenure,
            "product_name":            os.getenv("PRODUCT_NAME", "YourProduct"),
        },
    })


async def _personalize_decisions(decisions: list, pred_map: dict,
                                  customer_lookup: dict | None = None) -> list:
    if not ANTHROPIC_API_KEY:
        return decisions
    communicable = {"email", "call", "upgrade_offer"}
    semaphore    = asyncio.Semaphore(5)

    async def personalize_one(decision: dict) -> dict:
        if decision["action_type"] not in communicable:
            return decision
        prediction = pred_map.get(decision["customer_id"], {})
        payload    = _build_comms_payload(decision, prediction, customer_lookup)
        async with semaphore:
            raw = await asyncio.to_thread(_call_claude_sync, COMMS_SYSTEM_PROMPT, payload, 800)
        result = _parse_json(raw)
        if isinstance(result, dict) and "body" in result:
            decision = dict(decision)
            decision["personalized_content"] = result
        return decision

    logger.info("Personnalisation de %d communications…", len(decisions))
    results = await asyncio.gather(*[personalize_one(d) for d in decisions])
    done    = sum(1 for d in results if "personalized_content" in d)
    logger.info("Personnalisé : %d/%d", done, len(decisions))
    return list(results)


# ─── Full pipeline ────────────────────────────────────────────────────────────

async def run_full_pipeline(
    user_ids: list[str] | None = None,
    customer_lookup: dict | None = None,
) -> dict[str, Any]:
    """
    Pipeline complet v4.
    customer_lookup fourni par routes.py depuis la DB.
    """
    started_at = datetime.utcnow()

    dataset     = await data_agent.collect(user_ids=user_ids)
    analysis    = analysis_agent.run(dataset)
    predictions = prediction_agent.predict(analysis)
    decisions   = decision_agent.decide(predictions)
    pred_map    = {p["customer_id"]: p for p in predictions}

    logger.info("Pipeline Python: %d → %d à risque → %d décisions",
                len(dataset.get("subscriptions", [])), len(predictions), len(decisions))

    roi_preview  = finance_agent.calculate_roi(predictions, [])
    ceo_insights = await _call_ceo_agent(predictions, decisions, roi_preview)
    decisions    = _apply_ceo_overrides(decisions, ceo_insights)
    decisions    = await _personalize_decisions(decisions, pred_map, customer_lookup)
    action_results = await action_agent.execute(decisions)
    roi = finance_agent.calculate_roi(predictions, action_results)

    finished_at = datetime.utcnow()
    duration_s  = (finished_at - started_at).total_seconds()

    logger.info("Pipeline v4 terminé: %.1fs | %d actions | €%.0f sauvés | ROI %.1fx",
                duration_s, len(action_results),
                roi.get("total_revenue_saved", 0), roi.get("roi_ratio", 0))

    return {
        "pipeline": "churn_prevention_v4",
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": round(duration_s, 2),
        "claude_agents_used": bool(ANTHROPIC_API_KEY),
        "stages": {
            "data":       {"users_collected": len(dataset.get("subscriptions", []))},
            "analysis":   {"users_analysed": len(analysis)},
            "prediction": {"users_predicted": len(predictions)},
            "decision":   {"actions_decided": len(decisions),
                           "ceo_overrides": len(ceo_insights.get("edge_case_overrides", [])),
                           "patterns_found": len(ceo_insights.get("systemic_patterns", []))},
            "action":     {"actions_executed": len(action_results)},
        },
        "predictions":    predictions,
        "decisions":      decisions,
        "action_results": action_results,
        "roi":            roi,
        "ceo_insights":   ceo_insights,
    }
