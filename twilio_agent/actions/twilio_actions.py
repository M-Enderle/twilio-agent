import asyncio
import json
import logging
import time
from contextlib import contextmanager

from fastapi import Request
from fastapi.responses import HTMLResponse
from twilio.rest import Client
from twilio.twiml.voice_response import (Connect, Dial, Gather, Number,
                                         VoiceResponse)

from twilio_agent.actions.redis_actions import (agent_message, delete_job_info,
                                                get_job_info,
                                                get_location,
                                                get_next_caller_in_queue,
                                                get_service,
                                                get_shared_location,
                                                google_message, save_job_info,
                                                save_location, clear_caller_queue,
                                                add_to_caller_queue)
from twilio_agent.utils.eleven import cache_manager, generate_speech
from twilio_agent.utils.pricing import get_price
from twilio_agent.settings import settings

logger = logging.getLogger("TwilioActions")

# Initialize Twilio client
account_sid = settings.env.TWILIO_ACCOUNT_SID
auth_token = settings.env.TWILIO_AUTH_TOKEN.get_secret_value() if settings.env.TWILIO_AUTH_TOKEN else ""
server_url = settings.env.SERVER_URL

client = Client(account_sid, auth_token)


async def immediate_human_transfer(request: Request, caller_number: str, service: str) -> str:
    """Immediately transfer the caller to a human agent without further prompts."""
    with new_response() as response:
        say(
            response,
            settings.service(service).announcements.transfer_message
        )
        agent_message(caller_number, settings.service(service).announcements.transfer_message)
        save_job_info(caller_number, "Mitarbeiter angefordert", "Ja")
        dial = Dial(callerId=settings.service(service).phone_number)
        dial.append(Number(settings.service(service).emergency_contact.phone))
        response.append(dial)
        return send_request(request, response)


async def caller(request: Request, called: bool = False, service: str = None) -> str:
    form_data = await request.form()
    caller = form_data.get("Caller")
    if called or (service and caller == settings.service(service).phone_number):
        return form_data.get("Called")
    return caller


def send_request(request: Request, response: VoiceResponse):
    host = request.url.hostname
    connect = Connect()
    connect.stream(url=f"wss://{host}/media-stream")
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")


@contextmanager
def new_response():
    """Context manager to create a new TwiML VoiceResponse"""
    response = VoiceResponse()
    try:
        yield response
    finally:
        pass


def say(obj, text: str):
    if not text:
        return
    audio_bytes, duration = generate_speech(text)
    input_data = {"text": text}
    key = cache_manager.get_cache_key(input_data)
    url = f"{server_url}/audio/{key}.mp3"
    obj.play(url)


def send_sms_with_link(to: str):
    # Create location sharing link with caller parameter
    from twilio_agent.actions.location_sharing_actions import \
        generate_location_link
    from twilio_agent.actions.redis_actions import get_service

    # Get the service for this caller to use the correct phone number
    service = get_service(to)
    if not service:
        logger.error(f"Could not determine service for caller {to}, cannot send SMS")
        return

    from_number = settings.service(service).phone_number.phone_number

    location_link = generate_location_link(phone_number=to)["link_url"]

    message_body = f"""Hier ist die Notdienststation.
Teile deinen Standort mit diesem Link: {location_link}"""

    client.messages.create(
        body=message_body,
        from_=from_number,
        to=to,
    )

    logger.info(f"SMS with link sent to {to} from {from_number}")


def outbound_call_after_sms(to: str):
    location_data = get_shared_location(to)
    if not location_data:
        logger.error("No shared location available for %s; aborting outbound call", to)
        return

    latitude = location_data.get("latitude")
    longitude = location_data.get("longitude")
    if latitude is None or longitude is None:
        logger.error("Incomplete shared location for %s: %s", to, location_data)
        return

    try:
        latitude_float = float(latitude)
        longitude_float = float(longitude)
    except (TypeError, ValueError):
        logger.error("Invalid coordinate values for %s: %s", to, location_data)
        return

    maps_link = f"https://maps.google.com/?q={latitude},{longitude}"
    # Save Standort in the same structure used by Google Maps flow
    save_location(
        to,
        {
            "latitude": latitude_float,
            "longitude": longitude_float,
            "google_maps_link": maps_link,
        },
    )
    delete_job_info(to, "waiting_for_sms")
    delete_job_info(to, "hangup_reason")
    google_message(to, f"Live-Standort über SMS bestätigt: {maps_link}")

    # Get service for this caller
    service = get_service(to)
    if not service:
        logger.error(f"Could not determine service for caller {to}")
        return

    # Get pricing using the new service-based system
    try:
        price, duration, provider_name, provider_phone = get_price(service, longitude_float, latitude_float)
    except Exception as exc:
        logger.exception("Failed to compute price for %s (service: %s): %s", to, service, exc)
        return

    # Save pricing info
    save_job_info(to, "Preis", f"{price}€")
    save_job_info(to, "Wartezeit", f"{duration} Minuten")
    save_job_info(to, "Dienstleister", provider_name)
    save_job_info(to, "Dienstleister Telefon", provider_phone)

    # Populate contact queue for transfer
    clear_caller_queue(to)
    service_config = settings.service(service)
    locations = service_config.locations

    # Find matching location by provider name
    matching_location = None
    for location in locations:
        if location.name.lower() == provider_name.lower():
            matching_location = location
            break

    # Add contacts to queue
    if matching_location:
        sorted_contacts = sorted(matching_location.contacts, key=lambda c: c.position)
        for contact in sorted_contacts:
            if contact.name and contact.phone:
                add_to_caller_queue(to, contact.name, contact.phone)
                logger.info(f"Added contact {contact.name} to queue for {to}")
    else:
        # Fallback to emergency contact
        logger.warning(f"No location found for provider '{provider_name}', using emergency contact")
        emergency = service_config.emergency_contact
        if emergency.name and emergency.phone:
            add_to_caller_queue(to, emergency.name, emergency.phone)

    # Format pricing for speech using announcements
    from num2words import num2words

    price_words = num2words(price, lang="de")

    # Convert minutes to hours and minutes format
    hours = duration // 60
    remaining_minutes = duration % 60

    if hours > 0 and remaining_minutes > 0:
        hours_words = num2words(hours, lang="de")
        minutes_words = num2words(remaining_minutes, lang="de")
        hour_unit = "Stunde" if hours == 1 else "Stunden"
        minute_unit = "Minute" if remaining_minutes == 1 else "Minuten"
        if hours == 1:
            hours_words = "eine"
        if remaining_minutes == 1:
            minutes_words = "eine"
        duration_formatted = f"{hours_words} {hour_unit} und {minutes_words} {minute_unit}"
    elif hours > 0:
        hours_words = num2words(hours, lang="de")
        hour_unit = "Stunde" if hours == 1 else "Stunden"
        if hours == 1:
            hours_words = "eine"
        duration_formatted = f"{hours_words} {hour_unit}"
    else:
        minutes_words = num2words(remaining_minutes, lang="de")
        minute_unit = "Minute" if remaining_minutes == 1 else "Minuten"
        if remaining_minutes == 1:
            minutes_words = "eine"
        duration_formatted = f"{minutes_words} {minute_unit}"

    with new_response() as response:
        # Use service announcements for consistent messaging
        offer_message = settings.service(service).announcements.price_offer.format(
            price_words=price_words,
            minutes_words=duration_formatted
        )

        gather = Gather(
            input="speech",
            language="de-DE",
            action=f"{server_url}/parse-connection-request",
            speechTimeout="auto",
            speechModel="phone_call",
            enhanced=True,
            timeout=15,
        )
        say(gather, f"Hier ist die Notdienststation. Wir haben deinen Standort erhalten. {offer_message}")
        agent_message(to, f"SMS location confirmed. {offer_message}")
        response.append(gather)

        gather2 = Gather(
            input="speech",
            language="de-DE",
            action=f"{server_url}/parse-connection-request",
            speechTimeout="auto",
            speechModel="phone_call",
            enhanced=True,
            timeout=15,
        )
        say(gather2, settings.service(service).announcements.price_offer_prompt)
        response.append(gather2)

        say(
            response,
            "Leider konnte ich keine Eingabe erkennen. Ich verbinde dich mit einem Mitarbeiter.",
        )
        start_transfer(response, to)
        response.append(gather)

        # Get service to use correct phone number
        service_id = get_service(to)
        if not service_id:
            logger.error(f"Could not determine service for caller {to}")
            return
        from_number = settings.service(service_id).phone_number.phone_number

        client.calls.create(
            twiml=response,
            to=to,
            from_=from_number,
            record=True,
            recording_status_callback_method="POST",
            recording_status_callback=f"{server_url}/recording-status-callback/{to.replace('+', '00')}?source=followup",
            recording_status_callback_event="completed",
            status_callback=f"{server_url}/status",
            status_callback_event="completed",
        )


def send_job_details_sms(caller: str, transferred_to: str):
    """Send SMS with job details to the person who was transferred to"""

    try:
        location = get_location(caller)
    except (json.JSONDecodeError, TypeError, AttributeError):
        location = {}

    # Get service to use correct phone number
    service_id = get_service(caller)
    if not service_id:
        logger.error(f"Could not determine service for caller {caller}")
        return
    from_number = settings.service(service_id).phone_number.phone_number

    message_body = f"""Anrufdetails:
Anrufer: {caller}
Adresse: {location.get('formatted_address', 'Unbekannt')}
Preis: {get_job_info(caller, 'Preis')} Euro
Wartezeit: {get_job_info(caller, 'Wartezeit')} min
{location.get('google_maps_link', 'Unbekannt')}"""

    client.messages.create(
        body=message_body,
        from_=from_number,
        to=transferred_to,
    )
    logger.info(f"Job details SMS sent to {transferred_to}")


def start_transfer(response: VoiceResponse, caller: str) -> str:
    next_contact = get_next_caller_in_queue(caller)
    if not next_contact:
        return "no_more_agents"

    name = next_contact.get("name", "")
    phone = next_contact.get("phone", "")

    # Get service to use correct phone number and settings
    service_id = get_service(caller)
    if not service_id:
        logger.error(f"Could not determine service for caller {caller}")
        return "no_service"

    # Use configured ring timeout (unified for all contacts)
    timeout = settings.service(service_id).transfer_settings.ring_timeout
    caller_id = settings.service(service_id).phone_number.phone_number

    # URL-encode name for the callback
    from urllib.parse import quote
    tr = Dial(
        action=f"{server_url}/parse-transfer-call/{quote(name)}/{quote(phone)}",
        timeout=timeout,
        callerId=caller_id,
    )
    tr.append(Number(phone))
    response.append(tr)
    return "transferring"
