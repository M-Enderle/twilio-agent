import os
from contextlib import contextmanager
import logging

import dotenv
from fastapi import Request
from fastapi.responses import HTMLResponse
from twilio.rest import Client
from twilio.twiml.voice_response import Connect, Dial, Gather, Number, VoiceResponse

from twilio_agent.actions.redis_actions import get_shared_location, save_caller_contact
from twilio_agent.utils.pricing import get_price_towing_coordinates
from twilio_agent.utils.contacts import ContactManager

contact_manager = ContactManager()

dotenv.load_dotenv()
logger = logging.getLogger("uvicorn")

account_sid = os.environ["TWILIO_ACCOUNT_SID"]
auth_token = os.environ["TWILIO_AUTH_TOKEN"]
server_url = os.environ["SERVER_URL"]
twilio_phone_number = os.environ["TWILIO_PHONE_NUMBER"]

client = Client(account_sid, auth_token)


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
    from twilio_agent.actions.location_sharing_actions import generate_location_link

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
    if location_data:
        price, duration, provider, phone = get_price_towing_coordinates(
            location_data["longitude"], location_data["latitude"]
        )
        save_caller_contact(to, provider, phone)
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

        fallback_no_response(response)
        response.append(gather)

        call = client.calls.create(
            twiml=response,
            to=to,
            from_="+4915888647007",
        )


async def fallback_no_response(response: VoiceResponse, request: Request):
    say(
        response,
        "Leider konnte ich keine Eingabe erkennen. Ich verbinde dich mit einem Mitarbeiter.",
    )
    transfer(response, await caller(request))


def transfer(response: VoiceResponse, caller: str, name: str = None):
    if not name:
        from twilio_agent.actions.redis_actions import get_caller_contact
        contact = get_caller_contact(caller)
        if contact:
            name = contact["name"]
        else:
            name = "Andi"
    logger.info(f"Transferring call to {name}")
    tr = Dial()
    phone_number = contact_manager.get_phone(name)
    tr.append(Number(phone_number))
    response.append(tr)


if __name__ == "__main__":
    outbound_call_after_sms(to="+4917657888987")
