"""Twilio call/SMS interaction layer.

Provides TwiML response building, speech output, SMS sending,
outbound call handling, and call transfer orchestration.
"""

import logging
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import HTMLResponse
from num2words import num2words
from twilio.rest import Client
from twilio.twiml.voice_response import Connect, Dial, Gather, Number, VoiceResponse

from twilio_agent.actions.redis_actions import (
    add_to_caller_queue,
    agent_message,
    clear_caller_queue,
    delete_job_info,
    get_job_info,
    get_location,
    get_next_caller_in_queue,
    get_service,
    get_shared_location,
    google_message,
    save_job_info,
    save_location,
)
from twilio_agent.settings import settings
from twilio_agent.utils.eleven import cache_manager, generate_speech
from twilio_agent.utils.pricing import get_price

logger = logging.getLogger("TwilioActions")

# Initialize Twilio client
account_sid = settings.env.TWILIO_ACCOUNT_SID
auth_token = settings.env.TWILIO_AUTH_TOKEN.get_secret_value() if settings.env.TWILIO_AUTH_TOKEN else ""
server_url = settings.env.SERVER_URL

client = Client(account_sid, auth_token)


def _get_service_phone(caller: str) -> tuple[str, str] | None:
    """Return (service_id, from_number) for the caller, or None."""
    service_id = get_service(caller)
    if not service_id:
        logger.error("Could not determine service for caller %s", caller)
        return None
    from_number = settings.service(service_id).phone_number.phone_number
    return service_id, from_number


def _populate_contact_queue(caller: str, service: str, provider_name: str) -> None:
    """Fill the transfer queue with contacts matching the provider, or fallback to emergency."""
    clear_caller_queue(caller)
    service_config = settings.service(service)

    matching_location = None
    for location in service_config.locations:
        if location.name.lower() == provider_name.lower():
            matching_location = location
            break

    if matching_location:
        sorted_contacts = sorted(matching_location.contacts, key=lambda c: c.position)
        for contact in sorted_contacts:
            if contact.name and contact.phone:
                add_to_caller_queue(caller, contact.name, contact.phone)
                logger.info("Added contact %s to queue for %s", contact.name, caller)
    else:
        logger.warning("No location found for provider '%s', using emergency contact", provider_name)
        emergency = service_config.emergency_contact
        if emergency.name and emergency.phone:
            add_to_caller_queue(caller, emergency.name, emergency.phone)


def _format_duration_german(minutes: int) -> str:
    """Format a duration in minutes as German speech text."""
    hours = minutes // 60
    remaining = minutes % 60

    if hours > 0 and remaining > 0:
        hours_words = "eine" if hours == 1 else num2words(hours, lang="de")
        minutes_words = "eine" if remaining == 1 else num2words(remaining, lang="de")
        hour_unit = "Stunde" if hours == 1 else "Stunden"
        minute_unit = "Minute" if remaining == 1 else "Minuten"
        return f"{hours_words} {hour_unit} und {minutes_words} {minute_unit}"
    elif hours > 0:
        hours_words = "eine" if hours == 1 else num2words(hours, lang="de")
        hour_unit = "Stunde" if hours == 1 else "Stunden"
        return f"{hours_words} {hour_unit}"
    else:
        minutes_words = "eine" if remaining == 1 else num2words(remaining, lang="de")
        minute_unit = "Minute" if remaining == 1 else "Minuten"
        return f"{minutes_words} {minute_unit}"


async def immediate_human_transfer(request: Request, caller_number: str, service: str) -> str:
    """Immediately transfer the caller to a human agent without further prompts."""
    response = new_response()
    say(
        response,
        settings.service(service).announcements.transfer_message,
    )
    agent_message(caller_number, settings.service(service).announcements.transfer_message)
    save_job_info(caller_number, "Mitarbeiter angefordert", "Ja")

    # Try to find the closest provider if the caller has a location
    queue_populated = False
    location = get_location(caller_number)
    if location:
        latitude = location.get("latitude")
        longitude = location.get("longitude")
        if latitude and longitude:
            try:
                price, duration, provider_name, provider_phone = get_price(
                    service, float(longitude), float(latitude)
                )
                save_job_info(caller_number, "Dienstleister", provider_name)
                save_job_info(caller_number, "Dienstleister Telefon", provider_phone)
                _populate_contact_queue(caller_number, service, provider_name)
                queue_populated = True
            except Exception as exc:
                logger.warning(
                    "Could not calculate price for immediate transfer of %s: %s",
                    caller_number, exc,
                )

    # Fall back to emergency contact if no provider location found
    if not queue_populated:
        emergency = settings.service(service).emergency_contact
        if emergency.phone:
            emergency_name = emergency.name or "Notfallkontakt"
            clear_caller_queue(caller_number)
            add_to_caller_queue(caller_number, emergency_name, emergency.phone)
            save_job_info(caller_number, "Dienstleister", emergency_name)
            logger.info(
                "Immediate transfer for %s: using emergency contact %s (%s)",
                caller_number, emergency_name, emergency.phone,
            )

    # Use the standard transfer mechanism with action callbacks for tracking
    transfer_result = start_transfer(response, caller_number)
    if transfer_result == "no_more_agents":
        say(response, "Leider ist momentan niemand erreichbar. Bitte versuchen Sie es später erneut.")
        save_job_info(caller_number, "hangup_reason", "Keine Kontakte verfügbar")
        response.hangup()

    return send_request(request, response)


async def get_caller_number(request: Request, called: bool = False, service: str = None) -> str:
    """Extract the caller or called phone number from the Twilio request."""
    form_data = await request.form()
    caller_num = form_data.get("Caller")
    if called or (service and caller_num == settings.service(service).phone_number):
        return form_data.get("Called")
    return caller_num


def send_request(request: Request, response: VoiceResponse):
    host = request.url.hostname
    connect = Connect()
    connect.stream(url=f"wss://{host}/media-stream")
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")


def new_response() -> VoiceResponse:
    """Create a new TwiML VoiceResponse."""
    return VoiceResponse()


def say(obj: VoiceResponse | Gather, text: str) -> None:
    """Add speech output to a TwiML element via ElevenLabs TTS.

    Calls generate_speech to ensure the audio is cached on disk,
    then adds a <Play> pointing to the cached audio URL.
    """
    if not text:
        return
    audio_bytes, duration = generate_speech(text)
    input_data = {"text": text}
    key = cache_manager.get_cache_key(input_data)
    url = f"{server_url}/audio/{key}.mp3"
    obj.play(url)


def send_sms_with_link(to: str) -> None:
    """Send an SMS with a location-sharing link to the caller."""
    # Deferred import to avoid circular dependency with location_sharing_actions
    from twilio_agent.actions.location_sharing_actions import generate_location_link

    result = _get_service_phone(to)
    if not result:
        return
    _, from_number = result

    location_link = generate_location_link(phone_number=to)["link_url"]

    message_body = f"""Hier ist die Notdienststation.
Teile deinen Standort mit diesem Link: {location_link}"""

    client.messages.create(
        body=message_body,
        from_=from_number,
        to=to,
    )

    logger.info("SMS with link sent to %s from %s", to, from_number)


def outbound_call_after_sms(to: str) -> None:
    """Place an outbound call after the caller shares their location via SMS."""
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

    result = _get_service_phone(to)
    if not result:
        return
    service, from_number = result

    # Get pricing
    try:
        price, duration, provider_name, provider_phone = get_price(service, longitude_float, latitude_float)
    except Exception as exc:
        logger.exception("Failed to compute price for %s (service: %s): %s", to, service, exc)
        return

    save_job_info(to, "Preis", f"{price}€")
    save_job_info(to, "Wartezeit", f"{duration} Minuten")
    save_job_info(to, "Dienstleister", provider_name)
    save_job_info(to, "Dienstleister Telefon", provider_phone)

    # Populate contact queue for transfer
    _populate_contact_queue(to, service, provider_name)

    # Format pricing for speech
    price_words = num2words(price, lang="de")
    duration_formatted = _format_duration_german(duration)

    response = new_response()

    offer_message = settings.service(service).announcements.price_offer.format(
        price_words=price_words,
        minutes_words=duration_formatted,
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
    agent_message(to, f"{offer_message}")
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


def send_job_details_sms(caller: str, transferred_to: str) -> None:
    """Send SMS with job details to the person who was transferred to."""
    try:
        location = get_location(caller)
    except (TypeError, AttributeError):
        location = {}

    result = _get_service_phone(caller)
    if not result:
        return
    _, from_number = result

    recognized = get_job_info(caller, "Adresse erkannt") or ""
    formatted = location.get("formatted_address", "Unbekannt")

    address_lines = ""
    if not recognized:
        address_lines = f"Standort: {formatted}"

    message_body = f"""Anrufdetails:
Anrufer: {caller}
{address_lines}
Preis: {get_job_info(caller, 'Preis') or 'Unbekannt'}
Wartezeit: {get_job_info(caller, 'Wartezeit') or get_job_info(caller, 'Ankunftszeit') or 'Unbekannt'}
{location.get('google_maps_link', 'Unbekannt')}"""

    client.messages.create(
        body=message_body,
        from_=from_number,
        to=transferred_to,
    )
    logger.info("Job details SMS sent to %s", transferred_to)


def start_transfer(response: VoiceResponse, caller: str) -> str:
    """Append a <Dial> to the response to transfer the call to the next queued contact."""
    next_contact = get_next_caller_in_queue(caller)
    if not next_contact:
        return "no_more_agents"

    name = next_contact.get("name", "")
    phone = next_contact.get("phone", "")

    result = _get_service_phone(caller)
    if not result:
        return "no_service"
    service_id, caller_id = result

    timeout = settings.service(service_id).transfer_settings.ring_timeout

    tr = Dial(
        action=f"{server_url}/parse-transfer-call/{quote(name)}/{quote(phone)}",
        timeout=timeout,
        callerId=settings.service(service_id).phone_number,
    )
    tr.append(Number(phone))
    response.append(tr)
    return "transferring"
