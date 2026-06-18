"""
auth.py — API Key authentication middleware.

En mode développement (API_KEY absent du .env) : toutes les requêtes passent.
En production : toutes les routes protégées exigent l'header X-API-Key.

Usage dans routes.py :
    from auth import verify_api_key
    @router.get("/endpoint", dependencies=[Depends(verify_api_key)])
"""

import os
import logging
from fastapi import Security, HTTPException, status, Depends
from fastapi.security import APIKeyHeader

logger = logging.getLogger(__name__)

API_KEY = os.getenv("API_KEY", "")

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Security(_api_key_header)) -> None:
    """
    Dependency injectable dans les routes FastAPI.

    - Si API_KEY est vide dans .env → mode dev, pas d'auth.
    - Sinon → vérifie l'header X-API-Key.
    """
    if not API_KEY:
        # Dev mode — pas de clé configurée, accès libre
        return

    if not api_key or api_key != API_KEY:
        logger.warning("Unauthorized API access attempt")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Clé API invalide ou absente. Ajoutez l'header : X-API-Key: <votre-clé>",
            headers={"WWW-Authenticate": "ApiKey"},
        )
