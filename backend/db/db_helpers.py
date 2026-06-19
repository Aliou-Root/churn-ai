"""
db_helpers.py — Persistance des résultats pipeline en base PostgreSQL.

Fournit :
  - upsert_user()          : créer/mettre à jour un User depuis un stripe_customer_id
  - save_pipeline_results(): persister ChurnScore + ActionLog après un run
  - get_customer_lookup()  : récupérer nom/company/tenure pour personnalisation Claude
"""

import logging
import uuid as uuidlib
from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    ActionLog,
    ActionTypeEnum,
    ChurnScore,
    PipelineRun,
    RiskLevelEnum,
    User,
)

logger = logging.getLogger(__name__)


# ─── User upsert ──────────────────────────────────────────────────────────────

async def upsert_user(
    session: AsyncSession,
    stripe_customer_id: str,
    mrr: float = 0.0,
    plan: str = "starter",
) -> User:
    """
    Get or create a User from a Stripe customer ID.
    Updates MRR and last_seen_at if the user already exists.
    """
    result = await session.execute(
        select(User).where(User.stripe_customer_id == stripe_customer_id)
    )
    user = result.scalar_one_or_none()

    if not user:
        user = User(
            email=f"{stripe_customer_id}@placeholder.churnai",
            name=stripe_customer_id,
            stripe_customer_id=stripe_customer_id,
            mrr=mrr,
            plan=plan,
            is_active=True,
        )
        session.add(user)
        await session.flush()
        logger.debug("Created user: %s", stripe_customer_id)
    else:
        user.mrr = mrr
        user.plan = plan
        user.last_seen_at = datetime.now(timezone.utc)

    return user


# ─── Pipeline results persistence ─────────────────────────────────────────────

async def save_pipeline_results(
    session: AsyncSession,
    predictions: list,
    decisions: list,
    action_results: list,
) -> int:
    """
    Persist ChurnScore and ActionLog for every customer in the pipeline run.

    Returns the number of records saved.
    """
    action_map   = {a["customer_id"]: a for a in action_results}
    decision_map = {d["customer_id"]: d for d in decisions}

    saved = 0
    _valid_action_types = {e.value for e in ActionTypeEnum}

    for pred in predictions:
        cid  = pred["customer_id"]
        sub  = pred.get("subscription", {})
        plan = sub.get("plan", {})
        mrr  = plan.get("amount", 0) / 100  # Stripe stores in cents

        plan_name = "starter"
        if mrr >= 249:
            plan_name = "business"
        elif mrr >= 99:
            plan_name = "pro"

        try:
            user = await upsert_user(session, cid, mrr=mrr, plan=plan_name)

            # ── ChurnScore ──────────────────────────────────────────────────
            score_record = ChurnScore(
                user_id=user.id,
                score=pred["churn_score"],
                risk_level=RiskLevelEnum(pred["risk_level"]),
                factors={
                    "top_factors":  pred.get("top_factors", []),
                    "risk_signals": pred.get("risk_signals", {}),
                },
                revenue_at_risk=pred["revenue_at_risk"],
            )
            session.add(score_record)

            # ── ActionLog ───────────────────────────────────────────────────
            action   = action_map.get(cid)
            decision = decision_map.get(cid)

            if action and decision:
                action_type_str = action.get("action_type", "email")
                if action_type_str not in _valid_action_types:
                    action_type_str = "email"

                personalized = decision.get("personalized_content") or {}

                log = ActionLog(
                    user_id=user.id,
                    action_type=ActionTypeEnum(action_type_str),
                    payload={
                        "detail":   action.get("detail", ""),
                        "template": decision.get("template", ""),
                        "subject":  personalized.get("subject", ""),
                        "churn_score": pred["churn_score"],
                        "risk_level":  pred["risk_level"],
                    },
                    success=action.get("success", False),
                    revenue_saved=action.get("revenue_saved", 0.0),
                    ceo_override=bool(decision.get("ceo_override")),
                    claude_personalized=bool(action.get("claude_personalized")),
                )
                session.add(log)

            saved += 1

        except Exception as exc:
            logger.warning("Failed to persist results for %s: %s", cid, exc)
            continue

    try:
        await session.commit()
        logger.info("Persisted pipeline results: %d customers saved", saved)
    except Exception as exc:
        logger.error("DB commit failed: %s", exc)
        await session.rollback()

    return saved


# ─── Pipeline run snapshots (time-series) ──────────────────────────────────────

async def save_pipeline_run(session: AsyncSession, roi: dict, duration_seconds: float,
                            ai_used: bool) -> None:
    """Store one aggregated snapshot of a pipeline run for trend charts."""
    try:
        session.add(PipelineRun(
            users_at_risk    = roi.get("users_at_risk", 0),
            revenue_at_risk  = roi.get("total_revenue_at_risk", 0.0),
            revenue_saved    = roi.get("total_revenue_saved", 0.0),
            roi_ratio        = roi.get("roi_ratio", 0.0),
            avg_churn_score  = roi.get("avg_churn_score", 0.0),
            success_rate     = roi.get("success_rate", 0.0),
            actions_executed = roi.get("actions_executed", 0),
            duration_seconds = duration_seconds,
            ai_used          = ai_used,
        ))
        await session.commit()
    except Exception as exc:
        logger.warning("Failed to save pipeline run snapshot: %s", exc)
        await session.rollback()


async def get_pipeline_history(session: AsyncSession, limit: int = 30) -> list[dict]:
    """Return the most recent runs (oldest→newest) for charting."""
    result = await session.execute(
        select(PipelineRun).order_by(desc(PipelineRun.created_at)).limit(limit)
    )
    runs = list(result.scalars().all())
    runs.reverse()
    return [{
        "created_at":       r.created_at.isoformat() if r.created_at else None,
        "users_at_risk":    r.users_at_risk,
        "revenue_at_risk":  r.revenue_at_risk,
        "revenue_saved":    r.revenue_saved,
        "roi_ratio":        r.roi_ratio,
        "avg_churn_score":  r.avg_churn_score,
        "success_rate":     r.success_rate,
    } for r in runs]


# ─── Feedback loop: record real outcome of an action ────────────────────────────

async def record_action_outcome(session: AsyncSession, action_id: str,
                                 retained: bool, actual_revenue_saved: float | None) -> bool:
    """Mark whether a logged retention action actually prevented churn."""
    try:
        aid = uuidlib.UUID(str(action_id))
    except (ValueError, AttributeError):
        return False
    result = await session.execute(select(ActionLog).where(ActionLog.id == aid))
    log = result.scalar_one_or_none()
    if not log:
        return False
    log.retained = retained
    if actual_revenue_saved is not None:
        log.actual_revenue_saved = actual_revenue_saved
    log.outcome_recorded_at = datetime.now(timezone.utc)
    await session.commit()
    return True


# ─── Customer lookup ───────────────────────────────────────────────────────────

async def get_customer_lookup(
    session: AsyncSession,
    customer_ids: list[str],
) -> dict[str, dict]:
    """
    Build a lookup dict from DB User records:
        { stripe_customer_id: { name, company, days_as_customer } }

    Used by ceo_agent._build_comms_payload() to personalize Claude emails.
    Returns empty dict entries for customers not yet in DB.
    """
    if not customer_ids:
        return {}

    result = await session.execute(
        select(User).where(User.stripe_customer_id.in_(customer_ids))
    )
    users = result.scalars().all()

    now = datetime.now(timezone.utc)
    lookup: dict[str, dict] = {}

    for u in users:
        days = 0
        if u.created_at:
            created = u.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            days = max(0, (now - created).days)

        lookup[u.stripe_customer_id] = {
            "name":             u.name or u.stripe_customer_id,
            "company":          u.company or "",
            "days_as_customer": days,
        }

    return lookup
