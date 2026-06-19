"""
API Routes v4 — /analyze, /predict, /act, /dashboard, /insights, /pipeline/run, /health

Améliorations v4 :
  - Authentification API Key sur toutes les routes sensibles
  - Cache Redis 30min sur /dashboard (évite de relancer le pipeline à chaque F5)
  - Persistance DB après chaque run (/act, /pipeline/run)
  - customer_lookup depuis la DB transmis au pipeline
  - Endpoint /pipeline/run dédié pour les triggers explicites
  - /dashboard/refresh pour forcer le recalcul sans cache
"""

import json
import logging
import os
from typing import Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import config
from agents import analysis_agent, data_agent, decision_agent, prediction_agent
from agents.ceo_agent import run_full_pipeline
from auth import verify_api_key
from db.database import AsyncSessionLocal
from db.db_helpers import (
    get_customer_lookup,
    get_pipeline_history,
    record_action_outcome,
    save_pipeline_results,
    save_pipeline_run,
)
from ratelimit import limiter

logger = logging.getLogger(__name__)
router = APIRouter()

# ─── Redis cache ──────────────────────────────────────────────────────────────

REDIS_URL       = os.getenv("REDIS_URL", "redis://redis:6379/0")
CACHE_KEY       = "churnai:dashboard:latest"
CACHE_TTL       = 1800  # 30 minutes

_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    return _redis


async def get_cached_dashboard() -> dict | None:
    try:
        r   = await get_redis()
        raw = await r.get(CACHE_KEY)
        if raw:
            logger.info("Dashboard: cache hit")
            return json.loads(raw)
    except Exception as exc:
        logger.warning("Redis get failed: %s", exc)
    return None


async def set_cached_dashboard(data: dict) -> None:
    try:
        r = await get_redis()
        await r.set(CACHE_KEY, json.dumps(data), ex=CACHE_TTL)
        logger.info("Dashboard: cache mis à jour (TTL %ds)", CACHE_TTL)
    except Exception as exc:
        logger.warning("Redis set failed: %s", exc)


async def invalidate_cache() -> None:
    try:
        r = await get_redis()
        await r.delete(CACHE_KEY)
        logger.info("Dashboard: cache invalidé")
    except Exception as exc:
        logger.warning("Redis delete failed: %s", exc)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _build_dashboard_response(result: dict) -> dict:
    """Transforme le résultat pipeline en réponse dashboard."""
    roi         = result["roi"]
    predictions = result["predictions"]
    actions     = result["action_results"]
    ceo         = result.get("ceo_insights", {})

    churn_risk_list = [
        {
            "customer_id":          p["customer_id"],
            "churn_score":          p["churn_score"],
            "risk_level":           p["risk_level"],
            "revenue_at_risk":      p["revenue_at_risk"],
            "top_factors":          p["top_factors"],
            "predicted_churn_days": p["predicted_churn_days"],
        }
        for p in predictions
        if p["risk_level"] != "low"
    ]

    return {
        "kpis": {
            "users_at_risk":     roi["users_at_risk"],
            "revenue_at_risk":   roi["total_revenue_at_risk"],
            "revenue_saved":     roi["total_revenue_saved"],
            "actions_executed":  roi["actions_executed"],
            "actions_succeeded": roi["actions_succeeded"],
            "success_rate":      roi["success_rate"],
            "roi_ratio":         roi["roi_ratio"],
            "avg_churn_score":   roi["avg_churn_score"],
        },
        "breakdown_by_risk":  roi["breakdown_by_risk"],
        "churn_risk_list":    churn_risk_list,
        "top_saves":          roi["top_saves"],
        "recent_actions":     actions[:10],
        "pipeline_duration":  result["duration_seconds"],
        "claude_agents_used": result.get("claude_agents_used", False),
        "ceo_insights": {
            "health_score":       ceo.get("executive_summary", {}).get("health_score"),
            "immediate_priority": ceo.get("executive_summary", {}).get("immediate_priority"),
            "top_risks":          ceo.get("executive_summary", {}).get("top_risks", []),
            "product_team_flag":  ceo.get("executive_summary", {}).get("product_team_flag"),
            "systemic_patterns":  ceo.get("systemic_patterns", []),
            "ceo_overrides_count":len(ceo.get("edge_case_overrides", [])),
        },
    }


async def _run_and_persist(user_ids: list[str] | None = None) -> dict:
    """
    Exécute le pipeline complet, persiste en DB, met à jour le cache Redis.
    Appelé par /act et /pipeline/run.
    """
    async with AsyncSessionLocal() as session:
        # 1. Récupérer les données client depuis la DB pour personnalisation
        dataset = await data_agent.collect(user_ids=user_ids)
        all_cids = [s["customer"] for s in dataset.get("subscriptions", [])]
        customer_lookup = await get_customer_lookup(session, all_cids)

        # 2. Lancer le pipeline complet
        result = await run_full_pipeline(
            user_ids=user_ids,
            customer_lookup=customer_lookup,
        )

        # 3. Persister en base
        try:
            await save_pipeline_results(
                session,
                predictions=result["predictions"],
                decisions=result["decisions"],
                action_results=result["action_results"],
            )
            await save_pipeline_run(
                session,
                roi=result["roi"],
                duration_seconds=result.get("duration_seconds", 0.0),
                ai_used=result.get("claude_agents_used", False),
            )
        except Exception as exc:
            logger.error("Persistance DB échouée (pipeline continue): %s", exc)

    # 4. Mettre à jour le cache Redis
    dashboard_data = _build_dashboard_response(result)
    await set_cached_dashboard(dashboard_data)

    return result


# ─── Request schemas ──────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    user_ids: list[str] | None = None


class PredictRequest(BaseModel):
    user_ids: list[str] | None = None


class ActRequest(BaseModel):
    user_ids: list[str] | None = None
    dry_run:  bool = False


class PipelineRunRequest(BaseModel):
    user_ids: list[str] | None = None
    force_refresh: bool = False   # ignorer le cache existant


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/health")
async def health():
    """Health check public — pas d'auth."""
    return {
        "status":  "ok",
        "service": "ChurnAI API",
        "version": "4.0",
    }


@router.post("/analyze", dependencies=[Depends(verify_api_key)])
@limiter.limit("20/minute")
async def analyze(request: Request, req: AnalyzeRequest) -> dict[str, Any]:
    """Stage 1+2 : collecte + analyse comportementale."""
    dataset  = await data_agent.collect(user_ids=req.user_ids)
    analysis = analysis_agent.run(dataset)
    return {"users_analysed": len(analysis), "results": analysis}


@router.post("/predict", dependencies=[Depends(verify_api_key)])
@limiter.limit("20/minute")
async def predict(request: Request, req: PredictRequest) -> dict[str, Any]:
    """Stage 1+2+3 : collecte + analyse + prédictions churn."""
    dataset     = await data_agent.collect(user_ids=req.user_ids)
    analysis    = analysis_agent.run(dataset)
    predictions = prediction_agent.predict(analysis)
    return {"users_predicted": len(predictions), "predictions": predictions}


@router.post("/act", dependencies=[Depends(verify_api_key)])
@limiter.limit("10/minute")
async def act(request: Request, req: ActRequest) -> dict[str, Any]:
    """
    Pipeline complet.
    dry_run=True : simule sans exécuter et sans appeler Claude.
    dry_run=False : exécute, persiste en DB, met à jour le cache.
    """
    if req.dry_run:
        dataset     = await data_agent.collect(user_ids=req.user_ids)
        analysis    = analysis_agent.run(dataset)
        predictions = prediction_agent.predict(analysis)
        decisions   = decision_agent.decide(predictions)
        return {
            "dry_run": True,
            "actions_that_would_fire": len(decisions),
            "decisions": decisions,
        }

    result = await _run_and_persist(user_ids=req.user_ids)
    return result


@router.post("/pipeline/run", dependencies=[Depends(verify_api_key)])
@limiter.limit("10/minute")
async def pipeline_run(request: Request, req: PipelineRunRequest) -> dict[str, Any]:
    """
    Déclencheur explicite du pipeline.
    Utilisé par le bouton "Lancer les agents" du dashboard.
    Invalide le cache avant de relancer si force_refresh=True.
    """
    if req.force_refresh:
        await invalidate_cache()

    result = await _run_and_persist(user_ids=req.user_ids)
    return _build_dashboard_response(result)


@router.get("/dashboard", dependencies=[Depends(verify_api_key)])
async def dashboard() -> dict[str, Any]:
    """
    Données complètes pour le dashboard.

    Lit depuis le cache Redis si disponible (TTL 30min).
    Si cache vide → lance le pipeline complet et met en cache.
    Utiliser /dashboard/refresh pour forcer le recalcul.
    """
    cached = await get_cached_dashboard()
    if cached:
        return cached

    logger.info("Dashboard: cache miss, lancement du pipeline")
    result = await _run_and_persist()
    return _build_dashboard_response(result)


@router.post("/dashboard/refresh", dependencies=[Depends(verify_api_key)])
@limiter.limit("10/minute")
async def dashboard_refresh(request: Request) -> dict[str, Any]:
    """Force le recalcul du dashboard en ignorant le cache."""
    await invalidate_cache()
    result = await _run_and_persist()
    return _build_dashboard_response(result)


@router.get("/insights", dependencies=[Depends(verify_api_key)])
async def insights() -> dict[str, Any]:
    """CEO Agent insights seuls — plus léger que /dashboard."""
    cached = await get_cached_dashboard()
    if cached:
        return {
            "ceo_insights":    cached.get("ceo_insights", {}),
            "roi_snapshot":    cached.get("kpis", {}),
            "claude_agents_used": cached.get("claude_agents_used", False),
        }
    raise HTTPException(
        status_code=404,
        detail="Aucune donnée disponible. Lancez le pipeline d'abord via POST /pipeline/run"
    )


@router.get("/history", dependencies=[Depends(verify_api_key)])
async def history(limit: int = 30) -> dict[str, Any]:
    """Historique des runs (séries temporelles) pour les graphiques de tendance."""
    limit = max(1, min(limit, 90))
    async with AsyncSessionLocal() as session:
        runs = await get_pipeline_history(session, limit=limit)
    return {"count": len(runs), "runs": runs}


# ─── Runtime configuration ──────────────────────────────────────────────────

class ConfigUpdate(BaseModel):
    threshold_critical: float | None = None
    threshold_high:     float | None = None
    threshold_medium:   float | None = None
    tool_cost:          float | None = None
    product_name:       str | None = None


@router.get("/config", dependencies=[Depends(verify_api_key)])
async def get_config() -> dict[str, Any]:
    """Paramètres runtime actuels (seuils, coût outil, nom produit)."""
    return config.current()


@router.put("/config", dependencies=[Depends(verify_api_key)])
async def put_config(patch: ConfigUpdate) -> dict[str, Any]:
    """Met à jour les paramètres runtime et les persiste (Redis)."""
    r = await get_redis()
    updated = await config.update(r, patch.model_dump(exclude_none=True))
    await invalidate_cache()  # thresholds/cost affect the next pipeline output
    return updated


# ─── Feedback loop ────────────────────────────────────────────────────────────

class OutcomeRequest(BaseModel):
    retained: bool
    actual_revenue_saved: float | None = None


@router.post("/actions/{action_id}/outcome", dependencies=[Depends(verify_api_key)])
async def action_outcome(action_id: str, req: OutcomeRequest) -> dict[str, Any]:
    """Enregistre si une action de rétention a réellement évité le churn."""
    async with AsyncSessionLocal() as session:
        ok = await record_action_outcome(
            session, action_id, req.retained, req.actual_revenue_saved
        )
    if not ok:
        raise HTTPException(status_code=404, detail="Action introuvable")
    return {"action_id": action_id, "retained": req.retained, "recorded": True}


@router.get("/users/{customer_id}/risk", dependencies=[Depends(verify_api_key)])
async def user_risk(customer_id: str) -> dict[str, Any]:
    """Profil de risque d'un client spécifique."""
    dataset     = await data_agent.collect()
    analysis    = analysis_agent.run(dataset)
    predictions = prediction_agent.predict(analysis)

    match = next((p for p in predictions if p["customer_id"] == customer_id), None)
    if not match:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable dans les prédictions")
    return match
