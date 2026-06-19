"""
ChurnAI - SaaS Churn Prevention Platform
Multi-agent AI system powered by Claude Managed Agents + FastAPI
v4: scheduler APScheduler, logging structuré, validation env au démarrage
"""

import logging
import os
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.routes import router
from db.database import create_tables
from ratelimit import limiter
from webhooks import router as webhooks_router

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
        "ANTHROPIC_API_KEY": "moteur IA désactivé — pipeline fonctionne sans raisonnement IA",
        "STRIPE_SECRET_KEY": "Stripe non configuré — utilisation des données mock",
        "SENDGRID_API_KEY":  "SendGrid non configuré — emails simulés dans les logs",
        "API_KEY":           "Authentification désactivée — API ouverte (dev mode)",
    }

    for var in required:
        if not os.getenv(var):
            logger.error("Variable d'environnement REQUISE manquante : %s", var)
            sys.exit(1)

    # In production, refuse to start an unauthenticated, wide-open API.
    is_prod = os.getenv("APP_ENV", "development").lower() == "production"
    if is_prod and not os.getenv("API_KEY"):
        logger.error("APP_ENV=production mais API_KEY absent — refus de démarrer une API ouverte")
        sys.exit(1)
    if is_prod and os.getenv("CORS_ORIGINS", "*") == "*":
        logger.error("APP_ENV=production mais CORS_ORIGINS='*' — définissez les origines autorisées")
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

    # Config runtime (seuils, coût outil, nom produit) depuis Redis
    try:
        import config
        from api.routes import get_redis
        await config.load(await get_redis())
    except Exception as exc:
        logger.warning("Config non chargée depuis Redis (défauts utilisés): %s", exc)

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

# Rate limiting (SlowAPI)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — configurable. Defaults to open in dev; must be locked down in prod
# (enforced by _check_env). Example: CORS_ORIGINS="https://app.example.com,https://example.com"
_origins_env = os.getenv("CORS_ORIGINS", "*").strip()
_allow_origins = ["*"] if _origins_env in ("", "*") else [o.strip() for o in _origins_env.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=_allow_origins != ["*"],  # credentials + wildcard is invalid
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")
app.include_router(webhooks_router, prefix="/api/v1")


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
