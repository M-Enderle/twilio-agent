"""PocketID OIDC token validation middleware for the dashboard API."""

import hashlib
import logging
import os

import requests as http_requests
from fastapi import HTTPException, Request

from twilio_agent.actions.redis_actions import redis

logger = logging.getLogger("uvicorn")

POCKETID_USERINFO_URL = (
    os.getenv("POCKETID_ISSUER", "https://auth.pabst-andreas.de").rstrip("/")
    + "/api/oidc/userinfo"
)
# 7 days
TOKEN_CACHE_TTL = 7 * 24 * 3600
DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true"


def _cache_key(token: str) -> str:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    return f"notdienststation:auth_token:{token_hash}"


async def require_auth(request: Request) -> None:
    """FastAPI dependency that validates a PocketID access token."""

    # Skip auth in dev mode
    if DEV_MODE:
        return

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = auth_header[7:]  # Strip "Bearer "
    cache_key = _cache_key(token)

    # Check Redis cache first
    cached = redis.get(cache_key)
    if cached == b"valid":
        return

    # Validate against PocketID userinfo endpoint
    try:
        resp = http_requests.get(
            POCKETID_USERINFO_URL,
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
    except http_requests.RequestException as exc:
        logger.error("PocketID userinfo request failed: %s", exc)
        raise HTTPException(status_code=502, detail="Auth provider unreachable")

    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid access token")

    # Cache valid token
    redis.set(cache_key, "valid", ex=TOKEN_CACHE_TTL)
