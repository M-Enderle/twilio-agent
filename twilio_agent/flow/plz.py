import asyncio
import re
from fastapi import Request
from twilio_agent.settings import settings, HumanAgentRequested
from twilio_agent.actions.twilio_actions import immediate_human_transfer, new_response, send_request, say, send_sms_with_link
from twilio_agent.actions.redis_actions import (
    agent_message, get_service, save_job_info,
    save_location, user_message, ai_message, google_message
)
from twilio.twiml.voice_response import Gather
from twilio_agent.utils.ai import yes_no_question
from twilio_agent.utils.location_utils import get_geocode_result
from twilio_agent.utils.utils import call_info
from logging import getLogger

logger = getLogger("PLZFlow")


async def ask_plz_handler(request: Request) -> str:
    """Ask for PLZ via DTMF/speech."""
    caller_number, called_number, form_data = await call_info(request)
    service = get_service(caller_number)

    with new_response() as response:
        agent_message(caller_number, settings.service(service).announcements.zipcode_request)
        gather = Gather(
            input="dtmf speech",
            action="/process-plz",
            timeout=10,
            numDigits=5,
            language="de-DE",
            speechTimeout="auto",
            enhanced=True,
            model="experimental_conversations",
        )
        say(gather, settings.service(service).announcements.zipcode_request)
        response.append(gather)
        # Fallback: retry if no input received
        response.redirect(f"{settings.env.SERVER_URL}/ask-plz")
        return send_request(request, response)


async def process_plz_handler(request: Request) -> str:
    """Process PLZ input from DTMF or speech."""
    caller_number, called_number, form_data = await call_info(request)
    service = get_service(caller_number)

    # Extract PLZ from DTMF or speech
    digits = form_data.get("Digits", "")
    speech = form_data.get("SpeechResult", "")

    if digits:
        plz = str(digits)
        user_message(caller_number, f"DTMF PLZ: {plz}")
    elif speech:
        # Extract only digits from speech: "7 9 5 9 3." → "79593"
        plz = "".join(re.findall(r"\d", speech))
        user_message(caller_number, f"Speech PLZ: {speech} (cleaned: {plz})")
    else:
        logger.warning(f"No PLZ input received for caller {caller_number}")
        with new_response() as response:
            response.redirect(f"{settings.env.SERVER_URL}/ask-send-sms")
            return send_request(request, response)

    # Validate PLZ format (must be exactly 5 digits)
    if not plz or len(plz) != 5 or not plz.isdigit():
        logger.warning(f"Invalid PLZ format '{plz}' for caller {caller_number}")
        with new_response() as response:
            say(response, settings.service(service).announcements.plz_invalid_format)
            agent_message(caller_number, f"Invalid PLZ format: {plz}")
            response.redirect(f"{settings.env.SERVER_URL}/ask-plz")
            return send_request(request, response)

    # Validate PLZ by attempting geocoding
    try:
        location = await get_geocode_result(plz)
    except Exception as exc:
        logger.error("Error geocoding PLZ %s: %s", plz, exc)
        location = None

    if location and (location.plz or location.ort):
        # Validate the location is in Germany or Austria
        address_lower = (location.formatted_address or "").lower()
        if "germany" not in address_lower and "deutschland" not in address_lower and \
           "austria" not in address_lower and "österreich" not in address_lower:
            google_message(caller_number, f"PLZ {plz} liegt außerhalb des Servicegebiets: {location.formatted_address}")
            logger.warning(f"PLZ {plz} is outside service area (found: {location.formatted_address})")
            with new_response() as response:
                say(response, settings.service(service).announcements.plz_outside_area)
                agent_message(caller_number, f"PLZ outside service area: {location.formatted_address}")
                response.redirect(f"{settings.env.SERVER_URL}/ask-send-sms")
                return send_request(request, response)

        # Save location
        location_dict = location._asdict()
        location_dict["zipcode"] = location.plz
        location_dict["place"] = location.ort
        save_location(caller_number, location_dict)
        save_job_info(caller_number, "PLZ eingegeben", plz)

        google_message(caller_number, f"PLZ geocoded: {location.formatted_address}")

        # Proceed to pricing
        with new_response() as response:
            response.redirect(f"{settings.env.SERVER_URL}/start-pricing")
            return send_request(request, response)
    else:
        # Invalid PLZ - fallback to SMS
        google_message(caller_number, f"Keine Standortdaten für PLZ {plz} gefunden.")
        logger.warning(f"Invalid PLZ {plz} for caller {caller_number}, redirecting to SMS offer")
        with new_response() as response:
            say(response, settings.service(service).announcements.plz_not_found)
            agent_message(caller_number, f"PLZ not found: {plz}")
            response.redirect(f"{settings.env.SERVER_URL}/ask-send-sms")
            return send_request(request, response)


async def ask_send_sms_handler(request: Request) -> str:
    """Offer SMS location sharing."""
    caller_number, called_number, form_data = await call_info(request)
    service = get_service(caller_number)

    with new_response() as response:
        agent_message(caller_number, settings.service(service).announcements.sms_offer)
        gather = Gather(
            input="speech",
            action="/process-sms-offer",
            timeout=5,
            language="de-DE",
            speechTimeout="auto",
            enhanced=True,
            model="experimental_conversations",
        )
        say(gather, settings.service(service).announcements.sms_offer)
        response.append(gather)
        # Fallback: retry if no input received
        response.redirect(f"{settings.env.SERVER_URL}/ask-send-sms")
        return send_request(request, response)


async def process_sms_offer_handler(request: Request) -> str:
    """Process SMS offer response."""
    caller_number, called_number, form_data = await call_info(request)
    service = get_service(caller_number)

    transcription = form_data.get("SpeechResult", "")
    user_message(caller_number, transcription)

    try:
        accepts_sms, reasoning, duration, model_source = await asyncio.wait_for(
            yes_no_question(transcription, "SMS-Angebot"),
            timeout=6.0,
        )
        ai_message(caller_number, f"SMS offer response: {reasoning}", duration, model_source)

        if accepts_sms:
            # Send SMS with location sharing link
            send_sms_with_link(caller_number)
            save_job_info(caller_number, "SMS versendet", "Ja")

            with new_response() as response:
                say(response, settings.service(service).announcements.sms_sent_confirmation)
                agent_message(caller_number, "SMS sent with location sharing link. Ending call.")
                return send_request(request, response)
        else:
            # User declined SMS - transfer to human
            logger.info(f"Caller {caller_number} declined SMS offer, transferring to human")
            save_job_info(caller_number, "SMS versendet", "Nein - Kunde abgelehnt")
            return await immediate_human_transfer(request, caller_number, service)

    except asyncio.TimeoutError:
        ai_message(caller_number, "<SMS offer response timed out>", 6.0)
        logger.warning(f"SMS offer timeout for caller {caller_number}, transferring to human")
        return await immediate_human_transfer(request, caller_number, service)

    except HumanAgentRequested:
        logger.info(f"Caller {caller_number} requested human agent during SMS offer.")
        ai_message(caller_number, "<User requested human agent>", 0.0)
        return await immediate_human_transfer(request, caller_number, service)
