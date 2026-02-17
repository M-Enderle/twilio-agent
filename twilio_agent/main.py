"""FastAPI entry point that wires together the modular conversation flow."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from twilio_agent import configure_logging
from twilio_agent.api.dashboard import router as dashboard_router
from twilio_agent.conversation_flow import router as conversation_router
from twilio_agent.actions.location_sharing_actions import router as location_router
from twilio_agent.actions.recording_actions import router as recording_router
from twilio_agent.utils.eleven import cache_manager
from twilio_agent.scheduler import start_scheduler, stop_scheduler

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
        expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
    )

    application.include_router(dashboard_router, prefix="/api/dashboard")
    application.include_router(conversation_router)
    application.include_router(location_router)
    application.include_router(recording_router)

    @application.on_event("startup")
    async def startup_event():
        """Start background scheduler when the application starts."""
        logger.info("Starting background scheduler...")
        start_scheduler()

    @application.on_event("shutdown")
    async def shutdown_event():
        """Stop background scheduler when the application shuts down."""
        logger.info("Stopping background scheduler...")
        stop_scheduler()

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
