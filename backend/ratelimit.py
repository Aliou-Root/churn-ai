"""
ratelimit.py — shared SlowAPI limiter instance.

Kept in its own module so both main.py (handler registration) and
api/routes.py (per-endpoint decorators) can import it without a cycle.
Limits are disabled automatically when RATELIMIT_ENABLED is falsy (tests/dev).
"""

import os

from slowapi import Limiter
from slowapi.util import get_remote_address

RATELIMIT_ENABLED = os.getenv("RATELIMIT_ENABLED", "true").lower() in ("1", "true", "yes")

limiter = Limiter(
    key_func=get_remote_address,
    enabled=RATELIMIT_ENABLED,
    default_limits=[],
    # headers_enabled would require every limited endpoint to accept a
    # `response: Response` param; enforcement (429) works without it.
    headers_enabled=False,
)
