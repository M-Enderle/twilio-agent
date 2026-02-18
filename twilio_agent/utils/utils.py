from twilio_agent.settings import settings, VALID_SERVICES
from logging import getLogger
import datetime
import pytz
from fastapi import APIRouter, Request
from twilio_agent.actions.twilio_actions import get_caller_number as _get_caller

logger = getLogger("Utils")


async def get_caller_number(request: Request) -> str:
    """Return the caller phone number extracted from the current request."""
    return await _get_caller(request)


async def get_called_number(request: Request) -> str:
    """Return the called phone number extracted from the current request."""
    return await _get_caller(request, called=True)


async def call_info(request: Request) -> tuple[str, str]:
    """Extract relevant information from the incoming Twilio request."""
    caller_number = await get_caller_number(request)
    called_number = await get_called_number(request)
    form_data = await request.form()
    return caller_number, called_number, form_data


def which_service(phone_number_origin: str) -> str:
    """Determine the service category based on the caller's phone number."""
    phone_number_clean = phone_number_origin.replace(" ", "")
    logger.info(f"Determining service for called number: {phone_number_clean}")

    for service_id in VALID_SERVICES:
        service_phone = settings.service(service_id).phone_number.phone_number.replace(" ", "")
        logger.info(f"  Checking {service_id}: {service_phone}")
        if service_phone == phone_number_clean:
            logger.info(f"  ✓ Match found: {service_id}")
            return service_id

    logger.warning(f"Could not determine service for phone number: {phone_number_origin}")
    return None


def plz_fallback_path(service: str) -> str:
    """Return fallback URL path when address collection fails.
    notdienst-abschlepp skips PLZ and goes to SMS offer."""
    return "/ask-send-sms" if service == "notdienst-abschlepp" else "/ask-plz"


def direct_transfer(service: str) -> bool:
    """Check if direct transfer is enabled for the service."""
    service_settings = settings.service(service)

    active = service_settings.direct_forwarding.active
    start_time = service_settings.direct_forwarding.start_hour
    end_time = service_settings.direct_forwarding.end_hour
    current_hour = datetime.datetime.now(pytz.timezone("Europe/Berlin")).hour
    has_number = bool(service_settings.direct_forwarding.forward_phone)

    if active and has_number and (start_time <= current_hour < end_time):
        logger.info(f"Direct transfer is active for service '{service}' at hour {current_hour}.")
        return True
    
    logger.info(f"Direct transfer is not active for service '{service}' at hour {current_hour}.")
    return False


