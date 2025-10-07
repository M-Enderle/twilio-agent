import logging

import dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, Response
from twilio.twiml.voice_response import Gather
import asyncio

from twilio_agent.actions.location_sharing_actions import \
    router as location_router
from twilio_agent.actions.redis_actions import (add_to_caller_queue,
                                                agent_message, ai_message,
                                                clear_caller_queue,
                                                delete_next_caller, get_intent,
                                                get_job_info, get_location,
                                                get_transferred_to,
                                                init_new_call, save_job_info,
                                                save_location, set_intent,
                                                set_transferred_to,
                                                twilio_message, user_message,
                                                get_call_timestamp,
                                                save_call_recording,
                                                get_call_recording_binary)
from twilio_agent.actions.telegram_actions import send_telegram_notification
from twilio_agent.actions.twilio_actions import (caller, fallback_no_response,
                                                 new_response, say,
                                                 send_job_details_sms,
                                                 send_request,
                                                 send_sms_with_link,
                                                 start_transfer,
                                                 start_recording)
from twilio_agent.ui import router as ui_router
from twilio_agent.utils.ai import (classify_intent, extract_location,
                                   yes_no_question)
from twilio_agent.utils.contacts import ContactManager
from twilio_agent.utils.location_utils import check_location
from twilio_agent.utils.pricing import get_price_locksmith, get_price_towing
import httpx
import os

dotenv.load_dotenv()

app = FastAPI()
app.include_router(location_router)
app.include_router(ui_router)


class WebSocketLogFilter(logging.Filter):
    """Filter out noisy websocket connection logs from uvicorn."""

    keywords = ("WebSocket", "connection open", "connection closed")

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not any(keyword in message for keyword in self.keywords)


# Get uvicorn logger
logger = logging.getLogger("uvicorn")

# Configure logger to include datetime
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Attach websocket filter to uvicorn loggers
websocket_filter = WebSocketLogFilter()
for name in (
    "uvicorn",
    "uvicorn.access",
    "uvicorn.error",
    "uvicorn.protocols",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.wsproto_impl",
):
    logging.getLogger(name).addFilter(websocket_filter)

logger.info("Conversation flow started")


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring and load balancers"""
    return {
        "status": "healthy",
        "service": "twilio-agent",
        "timestamp": "2025-10-02T00:00:00Z",
    }


@app.api_route("/incoming-call", methods=["GET", "POST"])
async def incoming_call(request: Request):
    """Start of the Call"""
    caller_number = await caller(request)
    form_data = await request.form()

    init_new_call(caller_number)

    # Send Telegram notification with live UI link
    live_url = await send_telegram_notification(caller_number)
    logger.info(f"Telegram live UI URL: {live_url}")

    asyncio.create_task(start_recording(form_data.get('CallSid'), caller_number))

    logger.info("Incoming call from %s", request.headers.get("X-Twilio-Call-SID"))
    intent = get_intent(caller_number)

    previous_transferred_to = get_transferred_to(caller_number)
    with new_response() as response:
        if previous_transferred_to:
            save_job_info(caller_number, "Zuvor Angerufen", "Ja")
            save_job_info(
                caller_number,
                "Zuvor weitergeileitet an",
                previous_transferred_to,
            )
            with new_response() as response:
                add_to_caller_queue(caller_number, previous_transferred_to)
                start_transfer(response, caller_number)
                return send_request(request, response)
        else:
            if intent:
                save_job_info(caller_number, "Zuvor Angerufen", "Ja")
                save_job_info(caller_number, "Vorheriges Anliegen", intent)
            await add_locksmith_contacts(request)
            match intent:
                case "schlüsseldienst":
                    start_transfer(response, caller_number)
                    return send_request(request, response)
                case "abschleppdienst":
                    await add_towing_contacts(request)
                    start_transfer(response, caller_number)
                    return send_request(request, response)
                case _:
                    return await greeting(request)


async def greeting(request: Request):
    with new_response() as response:
        gather = Gather(
            input="speech",
            language="de-DE",
            action="/parse-intent-1",
            speechModel="deepgram_nova-3",
            speechTimeout="auto",
            timeout=15,
        )
        message = "Hallo, Schön das du bei uns anrufst. Du sprichst mit dem Assistent der Notdienststation, ich verbinde dich gleich mit dem richtigen Ansprechpartner! Wie kann ich dir helfen?"
        say(gather, message)
        agent_message(await caller(request), message)
        response.append(gather)
        gather2 = Gather(
            input="speech",
            language="de-DE",
            action="/parse-intent-1",
            speechModel="deepgram_nova-3",
            speechTimeout="auto",
            timeout=15,
        )
        say(
            gather2,
            "Bitte beschreibe dein Anliegen damit ich dich mit dem richtigen Ansprechpartner verbinden kann.",
        )
        response.append(gather2)
        await fallback_no_response(response, request)
        return send_request(request, response)


@app.api_route("/parse-intent-1", methods=["GET", "POST"])
async def parse_intent_1(request: Request):
    form_data = await request.form()
    speech_result = form_data.get("SpeechResult", "")
    user_message(await caller(request), speech_result)
    classification, duration = classify_intent(speech_result)
    ai_message(await caller(request), f"<Request classified as {classification}>", duration)
    match classification:
        case "schlüsseldienst":
            set_intent(await caller(request), "schlüsseldienst")
            return await address_query_locksmith(request)
        case "abschleppdienst":
            set_intent(await caller(request), "abschleppdienst")
            return await know_plz_towing(request)
        case "adac" | "mitarbeiter":
            with new_response() as response:
                start_transfer(response, await caller(request))
                return send_request(request, response)
        case _:
            return await intent_not_understood(request)


async def intent_not_understood(request: Request):
    with new_response() as response:
        gather = Gather(
            input="speech",
            language="de-DE",
            action="/parse-intent-2",
            speechModel="deepgram_nova-3",
            speechTimeout="auto",
            timeout=15,
        )
        message = (
            "Leider konnte ich deine Anfrage nicht verstehen. Wie kann ich dir helfen?"
        )
        say(gather, message)
        agent_message(await caller(request), message)
        response.append(gather)
        gather2 = Gather(
            input="speech",
            language="de-DE",
            action="/parse-intent-1",
            speechModel="deepgram_nova-3",
            speechTimeout="auto",
            timeout=15,
        )
        say(
            gather2,
            "Bitte beschreibe dein Anliegen damit ich dich mit dem richtigen Ansprechpartner verbinden kann.",
        )
        response.append(gather2)
        await fallback_no_response(response, request)
        return send_request(request, response)


@app.api_route("/parse-intent-2", methods=["GET", "POST"])
async def parse_intent_2(request: Request):
    form_data = await request.form()
    speech_result = form_data.get("SpeechResult", "")
    user_message(await caller(request), speech_result)
    classification, duration = classify_intent(speech_result)
    ai_message(await caller(request), f"<Request classified as {classification}>", duration)
    match classification:
        case "schlüsseldienst":
            set_intent(await caller(request), "schlüsseldienst")
            return await address_query_locksmith(request)
        case "abschleppdienst":
            set_intent(await caller(request), "abschleppdienst")
            return await know_plz_towing(request)
        case _:
            with new_response() as response:
                message = "Leider konnte ich dein Anliegen wieder nicht verstehen. Ich verbinde dich mit einem Mitarbeiter."
                agent_message(await caller(request), message)
                say(response, message)
                start_transfer(response, await caller(request))
                return send_request(request, response)


""" Locksmith conversation flow """


async def address_query_locksmith(request: Request):
    with new_response() as response:
        gather = Gather(
            input="speech",
            language="de-DE",
            action="/parse-location-locksmith",
            speechModel="deepgram_nova-3",
            speechTimeout="auto",
            timeout=15,
        )
        message = "Um die Kosten und Wartezeit zu berechnen, benötige ich deine Adresse. Bitte nenne mir Straße, Hausnummer, Postleitzahl und Ort."
        agent_message(await caller(request), message)
        say(gather, message)
        response.append(gather)
        gather2 = Gather(
            input="speech",
            language="de-DE",
            action="/parse-location-locksmith",
            speechModel="deepgram_nova-3",
            speechTimeout="auto",
            timeout=15,
        )
        say(gather2, "Bitte nenne mir Straße, Hausnummer, Postleitzahl und Ort.")
        response.append(gather2)
        await fallback_no_response(response, request)
        return send_request(request, response)


@app.api_route("/parse-location-locksmith", methods=["GET", "POST"])
async def parse_location_locksmith(request: Request):
    form_data = await request.form()
    speech_result = form_data.get("SpeechResult", "")
    user_message(await caller(request), speech_result)

    location, duration = extract_location(speech_result)
    logger.info("Location extracted: %s", location)

    ai_message(await caller(request), f"<Location extracted: {location}>", duration)
    location_keys_german = {
        "plz": "PLZ",
        "ort": "Ort",
        "strasse": "Straße",
        "hausnummer": "Hausnummer",
    }
    for key in location:
        if location[key]:
            save_job_info(
                await caller(request), location_keys_german.get(key, key), location[key]
            )

    location_result = check_location(location["plz"], location["ort"])
    with new_response() as response:
        if location_result:
            save_location(await caller(request), location_result)
            gather = Gather(
                input="speech",
                language="de-DE",
                action="/parse-location-correct-locksmith",
                speechModel="deepgram_nova-3",
                speechTimeout="auto",
                timeout=15,
            )
            message = (
                "Als Ort habe ich "
                + location_result["written_plz"]
                + " "
                + location_result["place"]
                + " erkannt. Ist das richtig?"
            )
            agent_message(await caller(request), message)
            say(gather, message)
            response.append(gather)
            gather2 = Gather(
                input="speech",
                language="de-DE",
                action="/parse-location-correct-locksmith",
                speechModel="deepgram_nova-3",
                speechTimeout="auto",
                timeout=15,
            )
            say(gather2, "Bitte bestätige, ob die Adresse korrekt ist.")
            response.append(gather2)
            await fallback_no_response(response, request)
            return send_request(request, response)
        else:
            gather = Gather(
                input="dtmf",
                action="/parse-location-numberblock-locksmith",
                timeout=10,
                numDigits=5,
            )
            message = "Ich konnte den Ort nicht finden. Bitte gib die Postleitzahl auf dem Nummernblock ein."
            agent_message(await caller(request), message)
            say(gather, message)
            response.append(gather)
            response.append(gather)
            gather2 = Gather(
                input="dtmf",
                action="/parse-location-numberblock-locksmith",
                timeout=10,
                numDigits=5,
            )
            say(gather2, "Bitte gib die Postleitzahl erneut ein.")
            response.append(gather2)
            await fallback_no_response(response, request)
            return send_request(request, response)


@app.api_route("/parse-location-correct-locksmith", methods=["GET", "POST"])
async def parse_location_correct_locksmith(request: Request):
    form_data = await request.form()
    speech_result = form_data.get("SpeechResult", "")
    correct, duration = yes_no_question(speech_result, "Der Kunde wurde gefragt ob die Adresse korrekt ist.")
    user_message(await caller(request), speech_result)
    with new_response() as response:
        if correct:
            return await calculate_cost_locksmith(request)
        else:
            gather = Gather(
                input="dtmf",
                action="/parse-location-numberblock-locksmith",
                numDigits=5,
                timeout=10,
            )
            message = "Bitte gib die Postleitzahl auf dem Nummernblock ein oder drücke die einz falls du deine Postleitzahl nicht kennst."
            agent_message(await caller(request), message)
            say(gather, message)
            response.append(gather)
            gather2 = Gather(
                input="dtmf",
                action="/parse-location-numberblock-locksmith",
                numDigits=5,
                timeout=10,
            )
            say(gather2, "Bitte gib die Postleitzahl erneut ein.")
            response.append(gather2)
            await fallback_no_response(response, request)
            return send_request(request, response)


@app.api_route("/parse-location-numberblock-locksmith", methods=["GET", "POST"])
async def parse_location_numberblock_locksmith(request: Request):
    form_data = await request.form()
    plz = form_data.get("Digits", "")
    save_job_info(await caller(request), "PLZ Tastatur", plz)
    user_message(await caller(request), plz)
    if len(str(plz)) > 3:
        location_result = check_location(plz, None)
        if location_result:
            save_location(await caller(request), location_result)
            return await calculate_cost_locksmith(request)
    message = "Ich leite dich an den Fahrer weiter."
    agent_message(await caller(request), message)
    with new_response() as response:
        say(response, message)
        start_transfer(response, await caller(request))
        return send_request(request, response)


async def calculate_cost_locksmith(request: Request):
    location = get_location(await caller(request))
    price, duration, provider, phone = get_price_locksmith(location)
    german_keys = {
        "price": "Preis",
        "duration": "Wartezeit",
        "provider": "Anbieter",
        "phone": "Telefon",
    }
    for key in ["price", "duration", "provider", "phone"]:
        save_job_info(await caller(request), german_keys[key], locals()[key])

    await add_locksmith_contacts(request)

    with new_response() as response:
        gather = Gather(
            input="speech",
            language="de-DE",
            action="/parse-connection-request-locksmith",
            speechModel="deepgram_nova-3",
            speechTimeout="auto",
            timeout=15,
        )
        message = f"Die Kosten betragen {price} Euro und die Wartezeit beträgt {duration} Minuten. Möchtest du jetzt verbunden werden?"
        agent_message(await caller(request), message)
        say(gather, message)
        response.append(gather)
        gather2 = Gather(
            input="speech",
            language="de-DE",
            action="/parse-connection-request-locksmith",
            speechModel="deepgram_nova-3",
            speechTimeout="auto",
            timeout=15,
        )
        say(gather2, "Bitte sage ja oder nein.")
        response.append(gather2)
        await fallback_no_response(response, request)
        return send_request(request, response)


@app.api_route("/parse-connection-request-locksmith", methods=["GET", "POST"])
async def parse_connection_request_locksmith(request: Request):
    form_data = await request.form()
    speech_result = form_data.get("SpeechResult", "")
    user_message(await caller(request), speech_result)
    connection_request, duration = yes_no_question(speech_result, "Der Kunde wurde gefragt ob er verbunden werden möchte.")
    ai_message(await caller(request), f"<Connection request: {connection_request}>", duration)
    if connection_request:
        save_job_info(await caller(request), "Weiterleitung angefordert", "Ja")
        with new_response() as response:
            start_transfer(response, await caller(request))
            return send_request(request, response)
    else:
        save_job_info(await caller(request), "Weiterleitung angefordert", "Nein")
        return await end_call(request)


""" Towing conversation flow """


async def know_plz_towing(request: Request):

    await add_towing_contacts(request)

    with new_response() as response:
        gather = Gather(
            input="speech",
            language="de-DE",
            action="/parse-know-plz-towing",
            speechModel="deepgram_nova-3",
            speechTimeout="auto",
            timeout=15,
        )
        message = "Kennst du die Postleitzahl von dem Ort an dem du gerade bist?"
        agent_message(await caller(request), message)
        say(gather, message)
        response.append(gather)
        gather2 = Gather(
            input="speech",
            language="de-DE",
            action="/parse-know-plz-towing",
            speechModel="deepgram_nova-3",
            speechTimeout="auto",
            timeout=15,
        )
        say(gather2, "Bitte sage ja oder nein.")
        response.append(gather2)
        await fallback_no_response(response, request)
        return send_request(request, response)


@app.api_route("/parse-know-plz-towing", methods=["GET", "POST"])
async def parse_know_plz_towing(request: Request):
    form_data = await request.form()
    speech_result = form_data.get("SpeechResult", "")
    user_message(await caller(request), speech_result)
    plz_known, duration = yes_no_question(speech_result, "Der Kunde wurde gefragt ob er die Postleitzahl des Ortes kennt.")
    ai_message(await caller(request), f"<PLZ known: {plz_known}>", duration)
    if plz_known:
        save_job_info(await caller(request), "PLZ bekannt", "Ja")
        return await ask_plz_towing(request)
    else:
        save_job_info(await caller(request), "PLZ bekannt", "Nein")
        return await ask_send_sms_towing(request)


async def ask_plz_towing(request: Request):
    with new_response() as response:
        gather = Gather(
            input="dtmf",
            action="/parse-plz-towing",
            timeout=10,
            numDigits=5,
        )
        message = "Bitte gib die Postleitzahl deines Ortes über den Nummernblock ein."
        agent_message(await caller(request), message)
        say(gather, message)
        response.append(gather)
        gather2 = Gather(
            input="dtmf",
            action="/parse-plz-towing",
            numDigits=5,
            timeout=10,
        )
        say(gather2, "Bitte gib die Postleitzahl erneut ein.")
        response.append(gather2)
        await fallback_no_response(response, request)
        return send_request(request, response)


@app.api_route("/parse-plz-towing", methods=["GET", "POST"])
async def parse_plz_towing(request: Request):
    form_data = await request.form()
    plz = form_data.get("Digits", "")
    save_job_info(await caller(request), "PLZ Tastatur", plz)

    user_message(await caller(request), plz)
    location = check_location(plz, None)

    with new_response() as response:
        if location:
            save_location(await caller(request), location)
            ai_message(
                await caller(request),
                f"<Location found: {location['place']}, {location['zipcode']}>",
            )
            return await calculate_cost_towing(request)
        else:
            ai_message(await caller(request), f"<Location not found for PLZ: {plz}>")
            gather = Gather(
                input="dtmf",
                action="/parse-plz-towing-retry",
                numDigits=5,
                timeout=10,
            )
            message = "Leider konnte ich den Ort nicht finden. Bitte gib die Postleitzahl erneut ein."
            agent_message(await caller(request), message)
            say(gather, message)
            response.append(gather)
            gather2 = Gather(
                input="dtmf",
                action="/parse-plz-towing-retry",
                numDigits=5,
                timeout=10,
            )
            say(gather2, "Bitte gib die Postleitzahl erneut ein.")
            response.append(gather2)
            await fallback_no_response(response, request)
            return send_request(request, response)


@app.api_route("/parse-plz-towing-retry", methods=["GET", "POST"])
async def parse_plz_towing_retry(request: Request):
    form_data = await request.form()
    plz = form_data.get("Digits", "")
    user_message(await caller(request), plz)
    save_job_info(await caller(request), "PLZ Tastatur Wiederholung", plz)
    location = check_location(plz, None)

    with new_response() as response:
        if location:
            save_location(await caller(request), location)
            ai_message(
                await caller(request),
                f"<Location found: {location['place']}, {location['zipcode']}>",
            )
            return await calculate_cost_towing(request)
        else:
            message = "Ich leite dich an den Fahrer weiter."
            agent_message(await caller(request), message)
            say(response, message)
            return send_request(request, response)


async def calculate_cost_towing(request: Request):
    location = get_location(await caller(request))
    price, duration, provider, phone = get_price_towing(location)
    german_keys = {
        "price": "Preis",
        "duration": "Wartezeit",
        "provider": "Anbieter",
        "phone": "Telefon",
    }
    for key in ["price", "duration", "provider", "phone"]:
        save_job_info(await caller(request), german_keys[key], locals()[key])

    with new_response() as response:
        gather = Gather(
            input="speech",
            language="de-DE",
            action="/parse-connection-request-towing",
            speechModel="deepgram_nova-3",
            speechTimeout="auto",
            timeout=15,
        )
        message = f"Die Kosten betragen {price} Euro und die Wartezeit beträgt {duration} Minuten. Möchtest du jetzt verbunden werden?"
        agent_message(await caller(request), message)
        say(gather, message)
        response.append(gather)
        gather2 = Gather(
            input="speech",
            language="de-DE",
            action="/parse-connection-request-towing",
            speechModel="deepgram_nova-3",
            speechTimeout="auto",
            timeout=15,
        )
        say(gather2, "Bitte sage ja oder nein.")
        response.append(gather2)
        await fallback_no_response(response, request)
        return send_request(request, response)


@app.api_route("/parse-connection-request-towing", methods=["GET", "POST"])
async def parse_connection_request_towing(request: Request):
    form_data = await request.form()
    speech_result = form_data.get("SpeechResult", "")
    user_message(await caller(request), speech_result)
    connection_request, duration = yes_no_question(speech_result, "Der Kunde wurde gefragt ob er verbunden werden möchte.")
    ai_message(await caller(request), f"<Connection request: {connection_request}>", duration)
    if connection_request:
        save_job_info(await caller(request), "Weiterleitung angefordert", "Ja")
        with new_response() as response:
            start_transfer(response, await caller(request))
            return send_request(request, response)
    else:
        save_job_info(await caller(request), "Weiterleitung angefordert", "Nein")
        return await end_call(request)


async def ask_send_sms_towing(request: Request):
    with new_response() as response:
        gather = Gather(
            input="speech",
            language="de-DE",
            action="/parse-send-sms-towing",
            speechModel="deepgram_nova-3",
            speechTimeout="auto",
            timeout=15,
        )
        message = "Wir können dir eine SMS mit einem Link zusenden, der uns deinen Standort übermittelt. Bist du damit einverstanden?"
        agent_message(await caller(request), message)
        say(gather, message)
        response.append(gather)
        gather2 = Gather(
            input="speech",
            language="de-DE",
            action="/parse-send-sms-towing",
            speechModel="deepgram_nova-3",
            speechTimeout="auto",
            timeout=15,
        )
        say(gather2, "Möchtest du eine SMS mit dem Link erhalten?")
        response.append(gather2)
        await fallback_no_response(response, request)
        return send_request(request, response)


@app.api_route("/parse-send-sms-towing", methods=["GET", "POST"])
async def parse_send_sms_towing(request: Request):
    form_data = await request.form()
    speech_result = form_data.get("SpeechResult", "")
    user_message(await caller(request), speech_result)
    send_sms_request, duration = yes_no_question(speech_result, "Der Kunde wurde gefragt ob er eine SMS mit dem Link erhalten möchte.")
    ai_message(await caller(request), f"<Send SMS request: {send_sms_request}>", duration)
    if send_sms_request:
        save_job_info(await caller(request), "SMS mit Link angefordert", "Ja")
        return await send_sms_towing(request)
    else:
        save_job_info(await caller(request), "SMS mit Link angefordert", "Nein")
        message = "Kein Problem. Ich leite dich an den Fahrer weiter."
        agent_message(await caller(request), message)
        with new_response() as response:
            say(response, message)
            start_transfer(response, await caller(request))
            return send_request(request, response)


async def send_sms_towing(request: Request):
    send_sms_with_link(await caller(request))
    with new_response() as response:
        message = "Wir haben soeben eine SMS mit dem Link versendet. Bitte öffne den Link und teile uns deinen Standort mit. Wir rufen dich anschließend zurück."
        agent_message(await caller(request), message)
        say(response, message)
        return send_request(request, response)


""" Call Handling """


async def add_locksmith_contacts(request: Request):
    clear_caller_queue(await caller(request))
    first_contact = get_job_info(await caller(request), "Anbieter") or "Andi"
    add_to_caller_queue(await caller(request), first_contact)
    add_to_caller_queue(await caller(request), "Jan")
    add_to_caller_queue(await caller(request), "Haas")
    save_job_info(
        await caller(request), "Anruf Warteschlange", f"{first_contact}, Jan, Haas"
    )


async def add_towing_contacts(request: Request):
    clear_caller_queue(await caller(request))
    add_to_caller_queue(await caller(request), "Markus")
    add_to_caller_queue(await caller(request), "Nils")
    add_to_caller_queue(await caller(request), "Oemer")
    save_job_info(await caller(request), "Anruf Warteschlange", "Markus, Nils, Ömer")


async def end_call(request: Request, with_message: bool = True):
    with new_response() as response:
        if with_message:
            message = "Vielen Dank für deinen Anruf. Wir wünschen dir noch einen schönen Tag. Auf Wiederhören!"
            agent_message(await caller(request), message)
            say(response, message)
        save_job_info(await caller(request), "Agent Anruf beendet", "Ja")
        response.hangup()
        return send_request(request, response)


@app.api_route("/status", methods=["GET", "POST"])
async def status(request: Request):
    save_job_info(await caller(request), "Live", "Nein")
    return JSONResponse(content={"status": "ok"})


@app.api_route("/parse-transfer-call/{name}", methods=["GET", "POST"])
async def parse_transfer_call(request: Request, name: str):
    form_data = await request.form()

    logger.info("Transfer call status: %s", form_data.get("DialCallStatus"))
    delete_next_caller(await caller(request))

    if form_data.get("DialCallStatus") != "completed":
        with new_response() as response:
            twilio_message(
                await caller(request),
                f"Weiterleitung an {name} fehlgeschlagen mit Status {form_data.get('DialCallStatus')}",
            )
            save_job_info(await caller(request), "Erfolgreich weitergeleitet", "Nein")
            status = start_transfer(response, await caller(request))

            if status == "no_more_agents":
                message = "Leider sind alle unsere Mitarbeiter im Gespräch. Bitte rufe später erneut an. Auf Wiederhören!"
                agent_message(await caller(request), message)
                say(response, message)
                response.hangup()

            return send_request(request, response)

    logger.info("Successfully transferred call to %s", name)
    save_job_info(await caller(request), "Erfolgreich weitergeleitet", "Ja")
    twilio_message(await caller(request), f"Erfolgreich weitergeleitet an {name}")

    # Send job details SMS to the person who was transferred to
    contact_manager = ContactManager()
    transferred_phone = contact_manager.get_phone(name)
    send_job_details_sms(await caller(request), transferred_phone)
    set_transferred_to(await caller(request), transferred_phone)
    save_job_info(await caller(request), "Weitergeleitet an", name)
    logger.info(f"Job details SMS sent to {transferred_phone}")

    with new_response() as response:
        response.hangup()
        return send_request(request, response)


@app.api_route("/recording-status-callback/{caller}", methods=["GET", "POST"])
async def recording_status_callback(request: Request, caller: str):
    form_data = await request.form()
    original_caller = caller
    if caller and caller.startswith("00"):
        original_caller = "+" + caller[2:]

    recording_url = form_data.get("RecordingUrl")
    if recording_url and form_data.get("RecordingStatus") == "completed":
        
        media_url = recording_url.replace(".json", ".mp3")
        logger.info("Downloading recording from %s", media_url)
        
        # Download the recording using Twilio credentials
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                media_url,
                auth=(account_sid, auth_token)
            )
            
            if response.status_code == 200:
                recording_data = response.content
                content_type = response.headers.get("Content-Type", "audio/mpeg")
                save_call_recording(original_caller, recording_data, content_type)
                logger.info(
                    "Recording downloaded and stored for %s (%d bytes)",
                    original_caller,
                    len(recording_data),
                )
            else:
                logger.error(
                    "Failed to download recording for %s. Status: %s",
                    original_caller,
                    response.status_code,
                )
    
    return JSONResponse(content={"status": "ok"})


@app.get("/recordings/{number}/{timestamp}")
async def fetch_recording(number: str, timestamp: str):
    audio_bytes, content_type = get_call_recording_binary(number, timestamp)
    if not audio_bytes:
        raise HTTPException(status_code=404, detail="Recording not found")

    return Response(content=audio_bytes, media_type=content_type)