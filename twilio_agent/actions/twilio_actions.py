import asyncio
import json
import logging
import os
import time
from contextlib import contextmanager

import dotenv
from fastapi import Request
from fastapi.responses import HTMLResponse
from twilio.rest import Client
from twilio.twiml.voice_response import (Connect, Dial, Gather, Number,
                                         VoiceResponse)

from twilio_agent.actions.redis_actions import (agent_message, get_intent,
                                                get_job_info,
                                                get_next_caller_in_queue,
                                                get_shared_location,
                                                delete_job_info,
                                                save_job_info, google_message,
                                                get_location)
from twilio_agent.utils.contacts import ContactManager
from twilio_agent.utils.pricing import (get_price_locksmith,
                                        get_price_towing_coordinates)

contact_manager = ContactManager()

dotenv.load_dotenv()
logger = logging.getLogger("uvicorn")

account_sid = os.environ["TWILIO_ACCOUNT_SID"]
auth_token = os.environ["TWILIO_AUTH_TOKEN"]
server_url = os.environ["SERVER_URL"]
twilio_phone_number = os.environ["TWILIO_PHONE_NUMBER"]

client = Client(account_sid, auth_token)

twilio_logger = logging.getLogger("twilio.http_client")
twilio_logger.setLevel(logging.WARNING)

httpx_logger = logging.getLogger("httpx")
httpx_logger.setLevel(logging.WARNING)


async def caller(request: Request):
    form_data = await request.form()
    caller = form_data.get("Caller")
    if caller == twilio_phone_number:
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
    obj.say(text, voice="Google.de-DE-Chirp3-HD-Charon", language="de-DE")


def send_sms_with_link(to: str):
    # Create location sharing link with caller parameter
    from twilio_agent.actions.location_sharing_actions import \
        generate_location_link

    location_link = generate_location_link(phone_number=to)["link_url"]

    message_body = f"""Hallo, hier ist die Notdienststation. 🚗⚠️
    
Bitte teile uns deinen Standort mit, indem du auf den folgenden Link klickst: {location_link} 📍"""

    client.messages.create(
        body=message_body,
        from_=twilio_phone_number,
        to=to,
    )
    
    logger.info(f"SMS with link sent to {to}")


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
    save_job_info(to, "Latitude", latitude)
    save_job_info(to, "Longitude", longitude)
    save_job_info(to, "Google Maps Link", maps_link)
    delete_job_info(to, "waiting_for_sms")
    delete_job_info(to, "hangup_reason")
    google_message(to, f"Live-Standort über SMS bestätigt: {maps_link}")

    intent = (get_intent(to) or "").lower()
    if intent != "schlüsseldienst":
        intent = "abschleppdienst"

    if intent == "schlüsseldienst":
        service_name = "Schlüsseldienst"
        pricing_fn = get_price_locksmith
        pricing_args = (longitude_float, latitude_float)
    else:
        service_name = "Abschleppdienst"
        pricing_fn = get_price_towing_coordinates
        pricing_args = (longitude_float, latitude_float)

    try:
        price, duration, provider, phone = pricing_fn(*pricing_args)
    except Exception as exc:
        logger.exception("Failed to compute %s price for %s: %s", intent, to, exc)
        return

    service_values = {
        "price": price,
        "duration": duration,
        "provider": provider,
        "phone": phone,
    }
    for key, german in {"price": "Preis", "duration": "Wartezeit", "provider": "Anbieter", "phone": "Telefon"}.items():
        value = service_values[key]
        if not value:
            logger.error("Missing %s for %s", key, service_name)
            return
        save_job_info(to, german, value)
    save_job_info(to, "Service", service_name)

    with new_response() as response:
        gather = Gather(
            input="speech",
            language="de-DE",
            action=f"{server_url}/parse-connection-request-unified",
            speechTimeout="auto",
            speechModel="phone_call",
            enhanced=True,
            timeout=15,
        )
        message = (
            "Hier ist die Notdienststation. Wir haben deinen Standort erhalten. "
            f"Der Preis für den {service_name} beträgt {price} Euro. "
            f"Die Ankunftszeit beträgt ungefähr {duration} Minuten. "
            f"Möchtest du den {service_name} jetzt beauftragen?"
        )
        say(gather, message)
        agent_message(to, message)
        response.append(gather)
        gather2 = Gather(
            input="speech",
            language="de-DE",
            action=f"{server_url}/parse-connection-request-unified",
            speechTimeout="auto",
            speechModel="phone_call",
            enhanced=True,
            timeout=15,
        )
        say(gather2, "Bitte sagen Sie Ja oder Nein.")
        response.append(gather2)

        say(
            response,
            "Leider konnte ich keine Eingabe erkennen. Ich verbinde dich mit einem Mitarbeiter.",
        )
        start_transfer(response, to)
        response.append(gather)

        client.calls.create(
            twiml=response,
            to=to,
            from_="+491604996655",
            record=True,
            recording_status_callback_method="POST",
            recording_status_callback=f"{server_url}/recording-status-callback/{to.replace('+', '00')}?source=followup",
            recording_status_callback_event="completed",
            status_callback=f"{server_url}/status",
            status_callback_event="completed",
        )


async def fallback_no_response(response: VoiceResponse, request: Request):
    say(
        response,
        "Leider konnte ich keine Eingabe erkennen. Ich verbinde dich mit einem Mitarbeiter.",
    )


def send_job_details_sms(caller: str, transferred_to: str):
    """Send SMS with job details to the person who was transferred to"""

    try:
        location = get_location(caller)
    except (json.JSONDecodeError, TypeError, AttributeError):
        location = {}

    message_body = f"""Anrufdetails:
📞 Anrufer: {caller}
📍 Erkannter Ort: {location.get('zipcode', '')} {location.get('place', '')}
💰 Genannter Preis: {get_job_info(caller, 'Preis')} Euro
⏰ Genannte Wartezeit: {get_job_info(caller, 'Wartezeit')} Minuten"""

    client.messages.create(
        body=message_body,
        from_=twilio_phone_number,
        to=transferred_to,
    )
    logger.info(f"Job details SMS sent to {transferred_to}")


def start_transfer(response: VoiceResponse, caller: str) -> str:
    next_caller = get_next_caller_in_queue(caller)
    if not next_caller:
        return "no_more_agents"
    tr = Dial(action=f"{server_url}/parse-transfer-call/{next_caller}", timeout=10, callerId=twilio_phone_number)
    phone_number = contact_manager.get_phone(next_caller)
    tr.append(Number(phone_number))
    response.append(tr)
    return "transferring"
