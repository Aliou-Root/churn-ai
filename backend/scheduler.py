"""
scheduler.py — Tâches planifiées avec APScheduler.

Tâche unique pour l'instant :
  - weekly_report_job : tous les lundis à 08:00 UTC
    → Agrège les données de la semaine depuis la DB
    → Appelle le Weekly Analyst Claude agent
    → Log le résultat (en production : envoyer par email ou Slack)

Pour ajouter une tâche :
    scheduler.add_job(ma_fonction, trigger=CronTrigger(...), id='mon_job')
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler(timezone="UTC")


# ─── Weekly report ────────────────────────────────────────────────────────────

async def run_weekly_report() -> None:
    """
    Rapport hebdomadaire ChurnAI.

    1. Récupère les ChurnScore et ActionLog des 7 derniers jours depuis la DB.
    2. Construit le payload pour le Weekly Analyst Agent.
    3. Appelle Claude via messages.create().
    4. Log le résultat (TODO: envoyer par email/Slack en production).
    """
    # Import ici pour éviter les circular imports au démarrage
    from sqlalchemy import select

    from agents.ceo_agent import WEEKLY_ANALYST_SYSTEM_PROMPT, _call_claude_sync, _parse_json
    from db.database import AsyncSessionLocal
    from db.models import ActionLog, ChurnScore

    logger.info("Weekly Analyst job started")
    week_end   = datetime.now(timezone.utc)
    week_start = week_end - timedelta(days=7)

    async with AsyncSessionLocal() as session:
        scores_res = await session.execute(
            select(ChurnScore).where(
                ChurnScore.created_at >= week_start,
                ChurnScore.created_at <= week_end,
            )
        )
        scores = scores_res.scalars().all()

        actions_res = await session.execute(
            select(ActionLog).where(
                ActionLog.executed_at >= week_start,
                ActionLog.executed_at <= week_end,
            )
        )
        actions = actions_res.scalars().all()

    if not scores:
        logger.info("Weekly Analyst: aucune donnée cette semaine, job ignoré")
        return

    # Agrégation
    risk_counts = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    for s in scores:
        key = s.risk_level.value if hasattr(s.risk_level, "value") else str(s.risk_level)
        risk_counts[key] = risk_counts.get(key, 0) + 1

    plan_dist = {"starter": 0, "pro": 0, "business": 0}
    # (à enrichir avec la jointure User si nécessaire)

    payload = json.dumps({
        "week_start":               week_start.isoformat(),
        "week_end":                 week_end.isoformat(),
        "daily_runs":               [],  # TODO: stocker les snapshots journaliers
        "total_customers_monitored":len({s.user_id for s in scores}),
        "plan_distribution":        plan_dist,
        "risk_breakdown":           risk_counts,
        "total_revenue_at_risk":    round(sum(s.revenue_at_risk for s in scores), 2),
        "total_revenue_saved":      round(sum(a.revenue_saved for a in actions if a.success), 2),
        "actions_taken":            len(actions),
        "actions_succeeded":        sum(1 for a in actions if a.success),
    })

    # Appel Claude en thread pour ne pas bloquer la boucle asyncio
    loop = asyncio.get_event_loop()
    raw  = await loop.run_in_executor(
        None,
        lambda: _call_claude_sync(WEEKLY_ANALYST_SYSTEM_PROMPT, payload, max_tokens=1500),
    )
    result = _parse_json(raw)

    if result:
        summary = result.get("week_summary", {})
        alert   = result.get("founder_alert")
        logger.info(
            "Weekly report: health=%s | change=%.1f | alert=%s",
            summary.get("overall_health", "—"),
            summary.get("health_score_change", 0),
            alert or "none",
        )
        if alert:
            logger.warning("⚠️  FOUNDER ALERT: %s", alert)
        # TODO: envoyer le rapport par email/Slack ici
    else:
        logger.warning("Weekly Analyst n'a retourné aucun résultat JSON valide")


# ─── Initialisation ───────────────────────────────────────────────────────────

def init_scheduler() -> AsyncIOScheduler:
    """
    Configure et démarre le scheduler.
    Appelé depuis main.py au démarrage de l'application.
    """
    scheduler.add_job(
        run_weekly_report,
        trigger=CronTrigger(
            day_of_week="mon",
            hour=8,
            minute=0,
            timezone="UTC",
        ),
        id="weekly_analyst",
        replace_existing=True,
        misfire_grace_time=3600,  # tolérance 1h si le serveur était arrêté
    )

    scheduler.start()
    next_run = scheduler.get_job("weekly_analyst").next_run_time
    logger.info("Scheduler démarré — prochain rapport hebdomadaire : %s", next_run)
    return scheduler
