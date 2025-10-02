import os
from contextlib import contextmanager

import dotenv
from fastapi import Request
from fastapi.responses import HTMLResponse
from twilio.rest import Client
from twilio.twiml.voice_response import Connect, VoiceResponse, Gather

from twilio_agent.utils.pricing import get_price_towing_coordinates
from twilio_agent.actions.redis_actions import get_shared_location, save_caller_contact

dotenv.load_dotenv()

account_sid = os.environ["TWILIO_ACCOUNT_SID"]
auth_token = os.environ["TWILIO_AUTH_TOKEN"]
client = Client(account_sid, auth_token)


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

    message_body = f"Bitte teile Ihren Standort über diesen Link: {location_link}"

    client.messages.create(
        body=message_body,
        from_="+4915888647007",
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
            action="https://9e4c482f86de.ngrok-free.app/parse-connection-request-towing",
            speechModel="deepgram_nova-3",
            speechTimeout="auto",
        )
        say(gather, f"Hier ist die Notdienststation. Wie haben deinen Standort erhalten. Der Preis für den Abschleppdienst beträgt {price} Euro. Die Ankunftszeit beträgt ungefähr {duration} Minuten. Möchtest du den Abschleppdienst jetzt beauftragen?")
        response.append(gather)
        client.calls.create(
            twiml=response,
            to=to,
            from_="+4915888647007",
        )


if __name__ == "__main__":
    outbound_call_after_sms(to="+4917657888987")