"""FastAPI entry point that wires together the modular conversation flow."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from twilio_agent import configure_logging
from twilio_agent.actions.location_sharing_actions import \
    router as location_router
from twilio_agent.api.dashboard import router as dashboard_router
from twilio_agent.actions.recording_actions import router as recording_router
from twilio_agent.flow.address import router as address_router
from twilio_agent.flow.call_entry import router as call_entry_router
from twilio_agent.flow.management import router as management_router
from twilio_agent.flow.sms_and_transfer import router as sms_router
from twilio_agent.utils.eleven import cache_manager

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Build the FastAPI application and register all flow routers."""

    configure_logging()

    application = FastAPI(title="Twilio Conversation Flow")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(dashboard_router, prefix="/api/dashboard")
    application.include_router(call_entry_router)
    application.include_router(address_router)
    application.include_router(sms_router)
    application.include_router(management_router)
    application.include_router(recording_router)
    application.include_router(location_router)

    @application.get("/audio/{key}.mp3")
    async def get_audio(key: str):
        """Serve cached audio snippets generated during the call flow."""

        data = cache_manager.get_by_key(key)
        if data is None:
            raise HTTPException(status_code=404, detail="Audio not found")
        return Response(content=data, media_type="audio/mpeg")
    
    @application.get("/health")
    async def health_check():
        """Simple health check used by monitoring and load balancers."""

        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return {
            "status": "healthy",
            "service": "twilio-agent",
            "timestamp": timestamp,
        }

    return application


app = create_app()

logger.info("Conversation flow application initialised")
