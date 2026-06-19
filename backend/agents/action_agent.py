"""
ActionAgent v2 — exécute les actions de rétention.

Nouveauté v2 : si decision["personalized_content"] est présent
(généré par Claude Communication Agent), il est utilisé à la place
des templates codés en dur.

Fallback automatique vers les templates v1 si Claude n'est pas configuré.
"""

import os
from datetime import datetime
from typing import Any

import httpx

SENDGRID_API_KEY  = os.getenv("SENDGRID_API_KEY", "")
FROM_EMAIL        = os.getenv("FROM_EMAIL", "noreply@churnai.io")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")


# ─── Fallback templates (v1 — utilisés si Claude absent) ─────────────────────

FALLBACK_TEMPLATES: dict[str, dict] = {
    "billing_failure_fix": {
        "subject": "⚠️ Action required — update your payment method",
        "body": (
            "Hi,\n\nWe noticed a payment issue on your account. "
            "Please update your payment method to keep enjoying your subscription.\n\n"
            "👉 Update now: {update_url}\n\nCheers,\nThe Team"
        ),
    },
    "reactivation_win_back": {
        "subject": "We miss you — here's what's new",
        "body": (
            "Hi,\n\nIt's been a while since we've seen you. "
            "Log in now and see what you've been missing → {login_url}\n\nCheers,\nThe Team"
        ),
    },
    "feature_education": {
        "subject": "Getting the most out of your subscription",
        "body": (
            "Hi,\n\nWe noticed you haven't explored some of our most powerful features yet.\n\n"
            "Book a free 20-min onboarding call: {booking_url}\n\nCheers,\nThe Team"
        ),
    },
    "cancel_intent_50off": {
        "subject": "Before you go — 50% off for 2 months",
        "body": (
            "Hi,\n\nWe noticed you've scheduled a cancellation. "
            "Here's a special offer: 50% off your next 2 months.\n\n"
            "Keep your account active: {offer_url}\n\nCheers,\nThe Team"
        ),
    },
    "csm_outreach": {
        "subject": "Let's chat — quick call about your account",
        "body": (
            "Hi,\n\nI'd love to connect for 15 minutes to make sure you're getting "
            "the most out of your subscription.\n\n"
            "👉 Pick a time: {booking_url}\n\nBest,\nThe Team"
        ),
    },
    "plan_upgrade_incentive": {
        "subject": "Unlock more — 1 month free upgrade",
        "body": (
            "Hi,\n\nYou're growing fast. Our next plan gives you everything you need "
            "with 1 month free.\n\nUpgrade: {upgrade_url}\n\nCheers,\nThe Team"
        ),
    },
}


# ─── Main execute function ────────────────────────────────────────────────────

async def execute(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Execute retention actions. Returns list of execution results."""
    results = []
    for decision in decisions:
        result = await _dispatch(decision)
        results.append(result)
    return results


async def _dispatch(decision: dict) -> dict:
    action_type = decision["action_type"]
    base_result = {
        "customer_id":   decision["customer_id"],
        "action_type":   action_type,
        "template":      decision.get("template"),
        "executed_at":   datetime.utcnow().isoformat(),
        "success":       False,
        "revenue_saved": _estimate_revenue_saved(decision),
        "detail":        "",
        "claude_personalized": "personalized_content" in decision,
    }

    try:
        if action_type == "email":
            detail = await _send_email(decision)
        elif action_type == "discount":
            detail = await _apply_discount(decision)
        elif action_type == "call":
            detail = await _schedule_call(decision)
        elif action_type == "notification":
            detail = await _send_notification(decision)
        elif action_type == "upgrade_offer":
            detail = await _send_upgrade_offer(decision)
        elif action_type == "no_action":
            detail = "No action required (CEO override)"
        elif action_type == "flag_for_review":
            detail = "[FLAGGED] Requires manual CSM review"
        else:
            detail = f"Unknown action type: {action_type}"

        base_result["success"] = True
        base_result["detail"]  = detail

    except Exception as exc:
        base_result["detail"] = f"Error: {exc}"

    return base_result


# ─── Action implementations ───────────────────────────────────────────────────

def _get_email_content(decision: dict) -> tuple[str, str]:
    """
    Returns (subject, body) — uses Claude personalized content if available,
    falls back to hardcoded templates.
    """
    personalized = decision.get("personalized_content")
    if personalized and personalized.get("body"):
        subject = personalized.get("subject", "We'd love to hear from you")
        body    = personalized["body"]
        return subject, body

    # Fallback to v1 templates
    template_key = decision.get("template", "reactivation_win_back")
    template     = FALLBACK_TEMPLATES.get(template_key, {})
    subject      = template.get("subject", "We'd love to hear from you")
    body         = template.get("body", "").format(
        update_url  = "https://app.example.com/billing",
        login_url   = "https://app.example.com",
        booking_url = "https://cal.example.com/book",
        offer_url   = "https://app.example.com/offer",
        upgrade_url = "https://app.example.com/upgrade",
    )
    return subject, body


async def _send_email(decision: dict) -> str:
    subject, body = _get_email_content(decision)
    is_personalized = "personalized_content" in decision

    if SENDGRID_API_KEY:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={"Authorization": f"Bearer {SENDGRID_API_KEY}"},
                json={
                    "personalizations": [
                        {"to": [{"email": f"{decision['customer_id']}@example.com"}]}
                    ],
                    "from": {"email": FROM_EMAIL},
                    "subject": subject,
                    "content": [{"type": "text/plain", "value": body}],
                },
                timeout=10,
            )
            source = "Claude-personalized" if is_personalized else "template"
            return f"SendGrid {resp.status_code} [{source}] subject: {subject}"
    else:
        source = "Claude-personalized" if is_personalized else "template"
        return f"[SIMULATED] Email sent [{source}] | Subject: '{subject}' | To: {decision['customer_id']}"


async def _apply_discount(decision: dict) -> str:
    if STRIPE_SECRET_KEY:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.stripe.com/v1/coupons",
                headers={"Authorization": f"Bearer {STRIPE_SECRET_KEY}"},
                data={"percent_off": 50, "duration": "repeating", "duration_in_months": 2},
                timeout=10,
            )
            coupon = resp.json()
            return f"Stripe coupon created: {coupon.get('id')}"
    return f"[SIMULATED] 50% discount (2 months) applied to {decision['customer_id']}"


async def _schedule_call(decision: dict) -> str:
    personalized = decision.get("personalized_content", {})
    briefing = personalized.get("csm_briefing", "") if personalized else ""
    briefing_note = f" | CSM briefing: {briefing}" if briefing else ""
    return f"[SIMULATED] CSM call scheduled for {decision['customer_id']} within 24h{briefing_note}"


async def _send_notification(decision: dict) -> str:
    return f"[SIMULATED] In-app notification sent to {decision['customer_id']}"


async def _send_upgrade_offer(decision: dict) -> str:
    subject, body = _get_email_content(decision)
    is_personalized = "personalized_content" in decision
    source = "Claude-personalized" if is_personalized else "template"
    return f"[SIMULATED] Upgrade offer [{source}] sent to {decision['customer_id']}"


def _estimate_revenue_saved(decision: dict) -> float:
    mrr   = decision.get("revenue_at_risk", 0.0)
    score = decision.get("churn_score", 0.5)
    return round(mrr * score * 0.60, 2)
