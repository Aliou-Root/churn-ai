"""Integration test for the full pipeline (demo mode) + webhook/config units."""

import hashlib
import hmac
import time

import config
import webhooks
from agents.ceo_agent import run_full_pipeline

# ─── full pipeline in demo mode (no AI key, no DB, no Redis) ────────────────────

async def test_full_pipeline_demo_mode():
    result = await run_full_pipeline()
    for key in ("predictions", "decisions", "action_results", "roi", "duration_seconds"):
        assert key in result
    assert len(result["predictions"]) == 20          # mock dataset size
    assert result["roi"]["users_at_risk"] >= 0
    assert isinstance(result["claude_agents_used"], bool)
    # every executed action carries a result
    assert len(result["action_results"]) == len(result["decisions"])


# ─── webhook signature verification ─────────────────────────────────────────────

def _sign(payload: bytes, secret: str, ts: int) -> str:
    signed = f"{ts}.{payload.decode()}".encode()
    v1 = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={v1}"


def test_webhook_signature_valid_and_invalid():
    secret = "whsec_test"
    payload = b'{"type":"invoice.payment_failed"}'
    ts = int(time.time())
    good = _sign(payload, secret, ts)
    assert webhooks._verify_signature(payload, good, secret) is True
    # tampered payload
    assert webhooks._verify_signature(b'{"type":"x"}', good, secret) is False
    # wrong secret
    assert webhooks._verify_signature(payload, good, "whsec_other") is False
    # stale timestamp
    old = _sign(payload, secret, ts - 10_000)
    assert webhooks._verify_signature(payload, old, secret) is False


# ─── config coercion / clamping ──────────────────────────────────────────────────

async def test_config_update_coerces_and_clamps():
    before = config.current()
    out = await config.update(None, {
        "threshold_critical": 1.8,    # clamps to 1.0
        "tool_cost": -50,             # clamps to 0.0
        "product_name": "X" * 200,    # truncated to 80
        "unknown_key": "ignored",
    })
    assert out["threshold_critical"] == 1.0
    assert out["tool_cost"] == 0.0
    assert len(out["product_name"]) == 80
    assert "unknown_key" not in out
    # restore defaults so test order doesn't matter
    await config.update(None, before)
