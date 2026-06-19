"""
webhooks.py — Inbound Stripe webhooks.

Reacts in real time to billing events instead of polling the Stripe API:
  • invoice.payment_failed        → a customer just hit a billing failure
  • customer.subscription.deleted → a customer churned / scheduled cancellation

The signature is verified manually (HMAC-SHA256 over `t.payload`) using the
Stripe signing scheme, so we depend on nothing beyond the stdlib. If
STRIPE_WEBHOOK_SECRET is unset we still accept events in dev but log a warning.
"""

import hashlib
import hmac
import json
import logging
import os
import time

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)
router = APIRouter()

STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
TOLERANCE_SECONDS = 300  # reject replayed events older than 5 min


def _verify_signature(payload: bytes, sig_header: str, secret: str) -> bool:
    """Verify a Stripe `Stripe-Signature` header against the raw body."""
    if not sig_header:
        return False
    try:
        parts = dict(
            item.split("=", 1) for item in sig_header.split(",") if "=" in item
        )
        timestamp = parts.get("t", "")
        signature = parts.get("v1", "")
        if not timestamp or not signature:
            return False
        if abs(time.time() - int(timestamp)) > TOLERANCE_SECONDS:
            logger.warning("Stripe webhook: timestamp outside tolerance")
            return False
        signed = f"{timestamp}.{payload.decode('utf-8')}".encode()
        expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
    except Exception as exc:
        logger.warning("Stripe signature parse error: %s", exc)
        return False


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request) -> dict:
    payload = await request.body()
    sig = request.headers.get("Stripe-Signature", "")

    if STRIPE_WEBHOOK_SECRET:
        if not _verify_signature(payload, sig, STRIPE_WEBHOOK_SECRET):
            raise HTTPException(status_code=400, detail="Invalid Stripe signature")
    else:
        logger.warning("STRIPE_WEBHOOK_SECRET non défini — signature non vérifiée (dev)")

    try:
        event = json.loads(payload)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = event.get("type", "unknown")
    obj = event.get("data", {}).get("object", {})
    customer = obj.get("customer") or obj.get("id")

    handled = {
        "invoice.payment_failed":        "billing_failure",
        "customer.subscription.deleted": "subscription_cancelled",
        "customer.subscription.updated": "subscription_updated",
    }

    if event_type in handled:
        logger.info("Stripe webhook: %s pour client %s → %s",
                    event_type, customer, handled[event_type])
        # Invalidate the cached dashboard so the next read reflects the change.
        try:
            from api.routes import invalidate_cache
            await invalidate_cache()
        except Exception:  # pragma: no cover - defensive
            pass
        return {"received": True, "handled": handled[event_type], "customer": customer}

    logger.info("Stripe webhook ignoré: %s", event_type)
    return {"received": True, "handled": None}
