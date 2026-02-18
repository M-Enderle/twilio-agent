from fastapi import Request
from fastapi.responses import HTMLResponse
from twilio_agent.settings import settings
from twilio_agent.actions.twilio_actions import new_response, say
from twilio_agent.actions.redis_actions import agent_message
from twilio_agent.utils.utils import call_info
import os
from logging import getLogger

logger = getLogger("EntryFlow")

async def greet(service: str, request: Request) -> str:
    """Return a greeting message for the caller based on the service."""
    greeting = settings.service(service).announcements.greeting
    caller_number, called_number, form_data = await call_info(request)
    response = new_response()
    logger.info(f"Greeting caller {caller_number} with message: '{greeting}'")
    say(response, greeting)
    agent_message(caller_number, greeting)
    response.redirect(f"{settings.env.SERVER_URL}/ask-adress")
    return HTMLResponse(content=str(response), media_type="application/xml")