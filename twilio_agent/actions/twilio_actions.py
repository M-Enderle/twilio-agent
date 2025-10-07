import logging
import os
from contextlib import contextmanager

import dotenv
from fastapi import Request
from fastapi.responses import HTMLResponse
from twilio.rest import Client
from twilio.twiml.voice_response import (Connect, Dial, Gather, Number,
                                         VoiceResponse)

from twilio_agent.actions.redis_actions import (get_job_info,
                                                get_next_caller_in_queue,
                                                get_shared_location,
                                                agent_message,
                                                user_message,
                                                save_job_info)
from twilio_agent.utils.contacts import ContactManager
from twilio_agent.utils.pricing import get_price_towing_coordinates
import time
import asyncio
import logging

contact_manager = ContactManager()

dotenv.load_dotenv()
logger = logging.getLogger("uvicorn")

account_sid = os.environ["TWILIO_ACCOUNT_SID"]
auth_token = os.environ["TWILIO_AUTH_TOKEN"]
server_url = os.environ["SERVER_URL"]
twilio_phone_number = os.environ["TWILIO_PHONE_NUMBER"]

client = Client(account_sid, auth_token)

twilio_logger = logging.getLogger('twilio.http_client')
twilio_logger.setLevel(logging.WARNING)

httpx_logger = logging.getLogger('httpx')
httpx_logger.setLevel(logging.WARNING)


async def start_recording(call_sid: str, caller: str):
    await asyncio.sleep(2)

    recording = client.calls(call_sid).recordings.create(
        recording_status_callback=server_url + f"/recording-status-callback/{caller.replace('+', '00')}",
        recording_status_callback_event="completed"
    )
    logger.info(f"Started recording for call {call_sid}: {recording.sid}")

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


def outbound_call_after_sms(to: str):
    location_data = get_shared_location(to)
    save_job_info(to, "Longitude", location_data["longitude"])
    save_job_info(to, "Latitude", location_data["latitude"])
    save_job_info(to, "Google Maps Link", f"https://maps.google.com/?q={location_data['latitude']},{location_data['longitude']}")
    user_message(to, f"https://maps.google.com/?q={location_data['latitude']},{location_data['longitude']}")
    if location_data:
        price, duration, provider, phone = get_price_towing_coordinates(
            location_data["longitude"], location_data["latitude"]
        )
        for key in ["price", "duration", "provider", "phone"]:
            if not locals()[key]:
                logger.error(f"Missing {key} for towing service")
                return
    with new_response() as response:
        gather = Gather(
            input="speech",
            language="de-DE",
            action=f"{server_url}/parse-connection-request-towing",
            speechModel="deepgram_nova-3",
            speechTimeout="auto",
            timeout=15,
        )
        message = f"Hier ist die Notdienststation. Wie haben deinen Standort erhalten. Der Preis für den Abschleppdienst beträgt {price} Euro. Die Ankunftszeit beträgt ungefähr {duration} Minuten. Möchtest du den Abschleppdienst jetzt beauftragen?"
        say(gather, message)
        agent_message(to, message)
        response.append(gather)
        gather2 = Gather(
            input="speech",
            language="de-DE",
            action=f"{server_url}/parse-connection-request-towing",
            speechModel="deepgram_nova-3",
            speechTimeout="auto",
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
            from_="+4915888647007",
        )


async def fallback_no_response(response: VoiceResponse, request: Request):
    say(
        response,
        "Leider konnte ich keine Eingabe erkennen. Ich verbinde dich mit einem Mitarbeiter.",
    )


def send_job_details_sms(caller: str, transferred_to: str):
    """Send SMS with job details to the person who was transferred to"""

    location = get_job_info(caller, "standort")
    if not location:
        location = {}

    message_body = f"""Anrufdetails:
📞 Anrufer: {caller}
📍 Erkannter Ort: {location.get('zipcode')} {location.get('place')}
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
    tr = Dial(action=f"{server_url}/parse-transfer-call/{next_caller}", timeout=10)
    phone_number = contact_manager.get_phone(next_caller)
    tr.append(Number(phone_number))
    response.append(tr)
    return "transferring"
