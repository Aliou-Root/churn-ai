"""
ChurnAI - SaaS Churn Prevention Platform
Multi-agent AI system powered by Claude Managed Agents + FastAPI
v4: scheduler APScheduler, logging structuré, validation env au démarrage
"""

import os
import logging
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db.database import create_tables
from api.routes import router

# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


# ─── Validation des variables d'environnement ─────────────────────────────────

def _check_env() -> None:
    """
    Vérifie les variables critiques au démarrage.
    Affiche des warnings pour les variables optionnelles manquantes.
    Ne bloque PAS le démarrage — le pipeline fonctionne en mode démo sans elles.
    """
    required = ["DATABASE_URL"]
    optional_warnings = {
        "ANTHROPIC_API_KEY": "Claude agents désactivés — pipeline fonctionne sans raisonnement IA",
        "STRIPE_SECRET_KEY": "Stripe non configuré — utilisation des données mock",
        "SENDGRID_API_KEY":  "SendGrid non configuré — emails simulés dans les logs",
        "API_KEY":           "Authentification désactivée — API ouverte (dev mode)",
    }

    for var in required:
        if not os.getenv(var):
            logger.error("Variable d'environnement REQUISE manquante : %s", var)
            sys.exit(1)

    for var, msg in optional_warnings.items():
        if not os.getenv(var):
            logger.warning("⚠️  %s non défini → %s", var, msg)

    logger.info("✅ Variables d'environnement vérifiées")


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    # Validation
    _check_env()

    # Tables PostgreSQL
    await create_tables()
    logger.info("✅ Tables PostgreSQL prêtes")

    # Scheduler APScheduler
    from scheduler import init_scheduler
    sched = init_scheduler()
    logger.info("✅ Scheduler démarré")

    yield  # ← l'app tourne ici

    # Arrêt propre
    if sched.running:
        sched.shutdown(wait=False)
        logger.info("Scheduler arrêté")


# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="ChurnAI API",
    description="Autonomous SaaS churn prevention powered by Claude Managed Agents",
    version="4.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # TODO: restreindre en production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


@app.get("/")
async def root():
    return {
        "service":  "ChurnAI",
        "version":  "4.0.0",
        "status":   "running",
        "docs":     "/docs",
        "auth":     "X-API-Key header required" if os.getenv("API_KEY") else "open (dev mode)",
        "claude":   "enabled" if os.getenv("ANTHROPIC_API_KEY") else "disabled (demo mode)",
    }


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
