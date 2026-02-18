import asyncio
import time
from fastapi import Request
from num2words import num2words
from twilio_agent.settings import settings, HumanAgentRequested
from twilio_agent.actions.twilio_actions import immediate_human_transfer, new_response, send_request, say
from twilio_agent.actions.redis_actions import (
    agent_message, get_service, get_transcription_text, save_job_info,
    save_location, user_message, ai_message, google_message
)
from twilio.twiml.voice_response import Record, Gather
from twilio_agent.utils.ai import process_location, yes_no_question, correct_plz
from twilio_agent.utils.location_utils import get_geocode_result, get_plz_from_coordinates
from twilio_agent.utils.utils import call_info, plz_fallback_path
from twilio_agent.utils.eleven import transcribe_speech
import threading
from logging import getLogger

logger = getLogger("AddressFlow")

async def ask_address_handler(request: Request) -> str:
    """Ask the caller for their address."""
    caller_number, called_number, form_data = await call_info(request)
    service = get_service(caller_number)

    response = new_response()
    say(response, settings.service(service).announcements.address_request)
    agent_message(caller_number, settings.service(service).announcements.address_request)
    response.append(
        Record(
            action="/process-address",
            timeout=4,
            playBeep=False,
            maxLength=10,
        )
    )
    return send_request(request, response)

async def process_address_handler(request: Request) -> str:
    """Process the address provided by the caller."""
    caller_number, called_number, form_data = await call_info(request)
    service = get_service(caller_number)

    recording_url = form_data.get("RecordingUrl")

    # No recording provided
    if not recording_url:
        logger.warning(f"No recording provided for caller {caller_number}, redirecting to PLZ")
        response = new_response()
        response.redirect(f"{settings.env.SERVER_URL}{plz_fallback_path(service)}")
        return send_request(request, response)

    # process recording
    recording_id = recording_url.rstrip("/").split("/")[-1]

    # process in background process 
    threading.Thread(target=transcribe_speech, args=(recording_id, caller_number)).start()

    response = new_response()
    say(response, settings.service(service).announcements.address_processing)
    agent_message(caller_number, settings.service(service).announcements.address_processing)
    response.redirect(f"{settings.env.SERVER_URL}/address-processed")
    return send_request(request, response)
    

async def address_processed_handler(request: Request) -> str:
    """Handle the case when the address has been processed."""
    caller_number, called_number, form_data = await call_info(request)
    service = get_service(caller_number)
    
    # wait up to 3 seconds for the transcription to be available
    for _ in range (30):
        transcription = get_transcription_text(caller_number)
        if transcription:
            break
        time.sleep(0.1)
    else:
        logger.warning(f"Transcription timeout for caller {caller_number}, redirecting to PLZ")
        response = new_response()
        response.redirect(f"{settings.env.SERVER_URL}{plz_fallback_path(service)}")
        return send_request(request, response)

    user_message(caller_number, transcription)
    logger.info(f"Transcription for caller {caller_number}: {transcription}")

    # Extract location from transcription using AI
    try:
        (
            contains_loc,
            contains_city_bool,
            knows_adress,
            extracted_address,
            duration,
            model_source,
        ) = await asyncio.wait_for(process_location(transcription), timeout=6.0)
    except asyncio.TimeoutError:
        ai_message(caller_number, "<Request timed out>", 6.0)
        logger.warning(f"Location processing timeout for caller {caller_number}, redirecting to PLZ")
        response = new_response()
        response.redirect(f"{settings.env.SERVER_URL}{plz_fallback_path(service)}")
        return send_request(request, response)
    except HumanAgentRequested:
        logger.info(f"Caller {caller_number} requested a human agent during address processing.")
        ai_message(caller_number, "<User requested human agent>", 0.0)
        return await immediate_human_transfer(request, caller_number, service)

    logger.info(
        f"Location processing completed in {duration:.2f} seconds.\n Extracted address: {extracted_address}\n"
        f"Contains location: {contains_loc}, Contains city: {contains_city_bool}, Knows address: {knows_adress}, Model source: {model_source}"
    )

    # Handle the case where no location was found in the transcription
    if knows_adress is not None and not knows_adress:
        ai_message(
            caller_number,
            f"<Location not known by caller: knows_location={knows_adress}>",
            duration,
            model_source,
        )
        logger.info(f"Caller {caller_number} does not know address, redirecting to SMS offer")
        response = new_response()
        response.redirect(f"{settings.env.SERVER_URL}/ask-send-sms")
        return send_request(request, response)

    # Handle the case where a location was found but could not be extracted
    if not contains_loc or not contains_city_bool:
        ai_message(
            caller_number,
            f"<Location extraction failed: contains_location={contains_loc}, contains_city={contains_city_bool}. Extracted address: {extracted_address}>",
            duration,
            model_source,
        )
        logger.info(f"Location extraction failed for caller {caller_number}, redirecting to PLZ")
        response = new_response()
        response.redirect(f"{settings.env.SERVER_URL}{plz_fallback_path(service)}")
        return send_request(request, response)

    ai_message(
        caller_number,
        f"<Location extracted: {extracted_address}>",
        duration,
        model_source,
    )

    # try to extract a real location
    try:
        location = await get_geocode_result(extracted_address)
    except Exception as exc:
        logger.error("Error getting geocode result: %s", exc)
        location = None

    if not location or (not location.plz and not location.ort):
        google_message(
            caller_number,
            f"Google Maps konnte die Adresse '{extracted_address}' nicht eindeutig finden.",
        )
        logger.info(f"Geocoding failed for caller {caller_number}, redirecting to PLZ")
        response = new_response()
        response.redirect(f"{settings.env.SERVER_URL}{plz_fallback_path(service)}")
        return send_request(request, response)

    parsed_location = extracted_address
    save_job_info(caller_number, "Adresse erkannt", parsed_location)

    if not parsed_location:
        logger.info(f"No valid address parsed for caller {caller_number}, redirecting to PLZ")
        response = new_response()
        response.redirect(f"{settings.env.SERVER_URL}{plz_fallback_path(service)}")
        return send_request(request, response)

    # Resolve a full 5-digit PLZ if Google returned an incomplete one
    resolved_plz = location.plz if (location.plz and len(str(location.plz).strip()) == 5) else None
    if not resolved_plz:
        # Try reverse geocoding ~100m to the east
        shifted_lon = location.longitude + 0.00134
        resolved_plz = await get_plz_from_coordinates(location.latitude, shifted_lon)
        if resolved_plz:
            logger.info(f"Resolved PLZ via coordinate shift: {resolved_plz}")
    if not resolved_plz:
        # Fall back to AI-based PLZ correction
        resolved_plz = await correct_plz(extracted_address or location.ort or "", location.latitude, location.longitude)
        if resolved_plz:
            logger.info(f"Resolved PLZ via AI correction: {resolved_plz}")

    location_dict = location._asdict()
    location_dict["zipcode"] = resolved_plz or location.plz
    location_dict["place"] = location.ort
    save_location(caller_number, location_dict)

    google_message(
        caller_number,
        f"Google Maps Ergebnis: {location.formatted_address} ({location.google_maps_link})",
    )

    # Convert postal code digits to German words (e.g., "87509" -> "acht sieben fünf null neun")
    plz_spoken = ""
    if resolved_plz:
        plz_digits = [num2words(int(d), lang="de") for d in str(resolved_plz) if d.isdigit()]
        plz_spoken = " ".join(plz_digits)

    # Combine postal code and place name, fallback to formatted address
    parts = [plz_spoken, location.ort]
    place_phrase = " ".join(filter(None, parts)) or location.formatted_address

    response = new_response()
    agent_message(
        caller_number,
        settings.service(service).announcements.address_confirm.format(place_phrase=place_phrase),
    )
    gather = Gather(
        input="speech",
        language="de-DE",
        action="/confirm-address",
        speechTimeout="auto",
        timeout=15,
        enhanced=True,
        model="experimental_conversations",
    )
    say(gather, settings.service(service).announcements.address_confirm.format(place_phrase=place_phrase))

    gather_2 = Gather(
        input="speech",
        language="de-DE",
        action="/confirm-address",
        speechTimeout="auto",
        timeout=15,
        enhanced=True,
        model="phone_call",
    )
    say(gather_2, settings.service(service).announcements.address_confirm_prompt)
    response.append(gather)
    response.append(gather_2)
    # Fallback: retry if no input received
    response.redirect(f"{settings.env.SERVER_URL}/ask-adress")

    return send_request(request, response)


async def confirm_address_handler(request: Request) -> str:
    """Handle the case when the address has been confirmed."""
    caller_number, called_number, form_data = await call_info(request)
    service = get_service(caller_number)

    transcription = form_data.get("SpeechResult", "")
    user_message(caller_number, transcription)

    try:
        is_correct, reasoning, duration, model_source = await asyncio.wait_for(
            yes_no_question(
                transcription,
                "Der Kunde wurde gefragt ob die Adresse korrekt ist.",
            ),
            timeout=6.0,
        )
        ai_message(caller_number, f"Address confirmation: {reasoning}", duration, model_source)

        response = new_response()
        if is_correct:
            # Redirect to pricing
            response.redirect(f"{settings.env.SERVER_URL}/start-pricing")
        else:
            # Fall back to PLZ
            response.redirect(f"{settings.env.SERVER_URL}{plz_fallback_path(service)}")
        return send_request(request, response)

    except asyncio.TimeoutError:
        ai_message(caller_number, "<Confirmation timed out>", 6.0)
        logger.warning(f"Address confirmation timeout for caller {caller_number}, redirecting to PLZ")
        response = new_response()
        # Fallback to PLZ on timeout
        response.redirect(f"{settings.env.SERVER_URL}{plz_fallback_path(service)}")
        return send_request(request, response)

    except HumanAgentRequested:
        logger.info(f"Caller {caller_number} requested human agent during address confirmation.")
        ai_message(caller_number, "<User requested human agent>", 0.0)
        return await immediate_human_transfer(request, caller_number, service)