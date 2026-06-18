"""
DataAgent — collects & normalises data from Stripe and product usage logs.

Output: structured dataset ready for AnalysisAgent.

v2: removed dead crewai/langchain/openai imports (were never called in collect()).
"""

import os
import httpx
from datetime import datetime, timedelta
from typing import Any


STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")


# ─── Stripe helpers ───────────────────────────────────────────────────────────

async def _fetch_stripe_subscriptions() -> list[dict]:
    """Pull active + cancelled subscriptions from Stripe."""
    if not STRIPE_SECRET_KEY:
        return _mock_stripe_data()

    url     = "https://api.stripe.com/v1/subscriptions"
    headers = {"Authorization": f"Bearer {STRIPE_SECRET_KEY}"}
    params  = {"limit": 100, "status": "all"}

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", [])


def _mock_stripe_data() -> list[dict]:
    """Mock Stripe data for development / demo purposes."""
    base = datetime.utcnow()
    return [
        {
            "id": f"sub_{i:04d}",
            "customer": f"cus_{i:04d}",
            "status": "active",
            "plan": {"amount": [4900, 14900, 29900][i % 3], "currency": "eur"},
            "current_period_end": (base + timedelta(days=30 - i * 2)).isoformat(),
            "cancel_at_period_end": i % 7 == 0,
        }
        for i in range(1, 21)
    ]


# ─── Main collect function ────────────────────────────────────────────────────

async def collect(user_ids: list[str] | None = None) -> dict[str, Any]:
    """
    Entry point called by the orchestration pipeline.

    Returns
    -------
    dict with keys:
        subscriptions : list of Stripe subscription dicts
        usage_summary : aggregated usage metrics per user
        raw_events    : list of recent product events
    """
    subscriptions = await _fetch_stripe_subscriptions()

    if user_ids:
        subscriptions = [
            s for s in subscriptions if s.get("customer") in user_ids
        ]

    usage_summary = _build_usage_summary(subscriptions)
    raw_events    = _generate_mock_events(subscriptions)

    return {
        "subscriptions": subscriptions,
        "usage_summary": usage_summary,
        "raw_events":    raw_events,
        "collected_at":  datetime.utcnow().isoformat(),
    }


def _build_usage_summary(subscriptions: list[dict]) -> list[dict]:
    import random, hashlib
    summaries = []
    for sub in subscriptions:
        cid  = sub["customer"]
        seed = int(hashlib.md5(cid.encode()).hexdigest(), 16) % 1000
        random.seed(seed)
        summaries.append({
            "customer_id":        cid,
            "logins_last_30d":    random.randint(0, 30),
            "features_used":      random.randint(1, 10),
            "support_tickets":    random.randint(0, 5),
            "last_login_days_ago":random.randint(0, 45),
            "billing_failures":   random.randint(0, 3),
        })
    return summaries


def _generate_mock_events(subscriptions: list[dict]) -> list[dict]:
    import random
    events      = []
    event_types = ["login", "feature_used", "export", "settings_changed", "api_call"]
    for sub in subscriptions[:10]:
        for _ in range(random.randint(2, 8)):
            events.append({
                "customer_id": sub["customer"],
                "type": random.choice(event_types),
                "ts": (datetime.utcnow() - timedelta(days=random.randint(0, 30))).isoformat(),
            })
    return events
