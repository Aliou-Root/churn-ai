"""
config.py — Runtime, mutable application settings.

Unlike environment variables (read once at boot), these values can be changed
at runtime from the dashboard Settings page and are persisted in Redis so they
survive restarts. The deterministic agents (prediction thresholds, finance tool
cost) read the in-memory snapshot synchronously via `current()`.

Flow:
  • startup        → load(redis)      populate the in-memory cache from Redis
  • PUT /config    → update(redis, …) write Redis + refresh the cache
  • pipeline run   → current()/get()  synchronous read, no I/O
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

CONFIG_KEY = "churnai:config"

DEFAULTS: dict = {
    "threshold_critical": 0.75,
    "threshold_high":     0.55,
    "threshold_medium":   0.30,
    "tool_cost":          149.0,
    "product_name":       os.getenv("PRODUCT_NAME", "ChurnAI"),
}

_current: dict = dict(DEFAULTS)


def current() -> dict:
    """Return a copy of the live settings (safe to mutate by the caller)."""
    return dict(_current)


def get(key: str):
    return _current.get(key, DEFAULTS.get(key))


def _coerce(patch: dict) -> dict:
    """Validate and coerce an incoming patch against the known schema."""
    clean: dict = {}
    for key, default in DEFAULTS.items():
        if key not in patch or patch[key] is None:
            continue
        value = patch[key]
        if isinstance(default, float):
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
            if key.startswith("threshold"):
                value = max(0.0, min(1.0, value))
            if key == "tool_cost":
                value = max(0.0, value)
        elif isinstance(default, str):
            value = str(value)[:80]
        clean[key] = value
    return clean


async def load(redis) -> dict:
    """Populate the in-memory cache from Redis at startup. Never raises."""
    global _current
    if redis is None:
        return current()
    try:
        raw = await redis.get(CONFIG_KEY)
        if raw:
            stored = json.loads(raw)
            _current = {**DEFAULTS, **_coerce(stored)}
            logger.info("Config chargée depuis Redis")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Config load failed, using defaults: %s", exc)
    return current()


async def update(redis, patch: dict) -> dict:
    """Apply a partial update, persist to Redis, refresh the cache."""
    global _current
    clean = _coerce(patch or {})
    _current = {**_current, **clean}
    if redis is not None:
        try:
            await redis.set(CONFIG_KEY, json.dumps(_current))
            logger.info("Config mise à jour: %s", list(clean.keys()))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Config persist failed: %s", exc)
    return current()
