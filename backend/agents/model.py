"""
model.py — Churn probability model.

Replaces the pure heuristic with a real scikit-learn classifier when scikit-learn
is available. The model is trained once (lazily, in-process) on a synthetic but
realistic labelled dataset, then cached for the lifetime of the worker.

Design goals:
  • Zero external artifacts to ship — the model is reproducible from a fixed seed.
  • Graceful fallback — if scikit-learn is not installed, callers fall back to
    the deterministic heuristic in prediction_agent. `predict_proba()` returns
    None in that case.

Feature vector (order matters — see FEATURES):
  last_login_days_ago, logins_last_30d, features_used,
  support_tickets, billing_failures, cancel_intent
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

FEATURES = [
    "last_login_days_ago",
    "logins_last_30d",
    "features_used",
    "support_tickets",
    "billing_failures",
    "cancel_intent",
]

_model = None          # trained estimator (or None)
_loaded = False        # have we attempted to load/train yet?


def _generate_dataset(n: int = 4000, seed: int = 42):
    """Synthesize a labelled training set whose churn probability follows a
    sensible ground-truth function of the behavioural features (+ noise)."""
    import numpy as np

    rng = np.random.default_rng(seed)
    last_login = rng.integers(0, 90, n)
    logins     = rng.integers(0, 30, n)
    features   = rng.integers(0, 12, n)
    tickets    = rng.integers(0, 6, n)
    billing    = rng.integers(0, 4, n)
    cancel     = rng.integers(0, 2, n)

    # Ground-truth log-odds of churn (hand-tuned, monotonic where expected).
    logit = (
        -2.2
        + 0.045 * last_login
        - 0.10  * logins
        - 0.18  * features
        + 0.35  * tickets
        + 0.7   * billing
        + 2.4   * cancel
    )
    p = 1.0 / (1.0 + np.exp(-logit))
    y = (rng.random(n) < p).astype(int)

    X = np.column_stack([last_login, logins, features, tickets, billing, cancel]).astype(float)
    return X, y


def _train():
    """Train and return a calibrated logistic-regression pipeline, or None."""
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
    except Exception as exc:
        logger.info("scikit-learn indisponible (%s) — fallback heuristique", exc)
        return None

    X, y = _generate_dataset()
    pipe = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
    pipe.fit(X, y)
    logger.info("Modèle de churn entraîné (n=%d, acc≈%.3f)", len(y), pipe.score(X, y))
    return pipe


def _ensure_loaded():
    global _model, _loaded
    if not _loaded:
        _model = _train()
        _loaded = True


def is_ready() -> bool:
    _ensure_loaded()
    return _model is not None


def predict_proba(usage: dict, cancel_intent: bool) -> Optional[float]:
    """Return P(churn) in [0,1] for one customer, or None if no model."""
    _ensure_loaded()
    if _model is None:
        return None
    try:
        import numpy as np
        row = np.array([[
            float(usage.get("last_login_days_ago", 0)),
            float(usage.get("logins_last_30d", 0)),
            float(usage.get("features_used", 0)),
            float(usage.get("support_tickets", 0)),
            float(usage.get("billing_failures", 0)),
            float(1 if cancel_intent else 0),
        ]])
        return float(_model.predict_proba(row)[0][1])
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("predict_proba failed, fallback: %s", exc)
        return None
