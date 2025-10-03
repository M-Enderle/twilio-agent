import logging
import os

import dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from twilio.twiml.voice_response import Dial, Gather, Number

from twilio_agent.actions.location_sharing_actions import router as location_router
from twilio_agent.actions.redis_actions import (
    agent_message,
    ai_message,
    get_caller_contact,
    get_intent,
    get_location,
    save_caller_contact,
    save_caller_info,
    save_location,
    set_intent,
    user_message,
)
from twilio_agent.actions.twilio_actions import (
    fallback_no_response,
    new_response,
    say,
    send_request,
    send_sms_with_link,
    transfer,
    caller
)
from twilio_agent.utils.ai import classify_intent, extract_location, yes_no_question
from twilio_agent.utils.location_utils import check_location
from twilio_agent.utils.pricing import get_price_locksmith, get_price_towing

dotenv.load_dotenv()

app = FastAPI()
app.include_router(location_router)

# Get uvicorn logger
logger = logging.getLogger("uvicorn")
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

    form_data = await request.form()
    save_caller_info(await caller(request), form_data)

    logger.info("Incoming call from %s", request.headers.get("X-Twilio-Call-SID"))
    intent = get_intent(await caller(request))  # TODO: Check this

    intent = None  # TODO: Test remove !!!!!!

    match intent:
        case "schlüsseldienst":
            return await call_locksmith(request)
        case "abschleppdienst":
            return await call_towing_service(request)
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
        # message = "Hallo, Schön das du bei uns anrufst. Du sprichst mit dem Assistent der Notdienststation, ich verbinde dich gleich mit dem richtigen Ansprechpartner! Wie kann ich dir helfen?"
        message = "Hi"  # TODO: Test
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
    classification = classify_intent(speech_result)
    ai_message(await caller(request), f"<Request classified as {classification}>")
    match classification:
        case "schlüsseldienst":
            set_intent(await caller(request), "schlüsseldienst")
            return await address_query_locksmith(request)
        case "abschleppdienst":
            set_intent(await caller(request), "abschleppdienst")
            return await know_plz_towing(request)
        case "adac" | "mitarbeiter":
            return await call_locksmith(request)
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
    classification = classify_intent(speech_result)
    ai_message(await caller(request), f"<Request classified as {classification}>")
    match classification:
        case "schlüsseldienst":
            set_intent(await caller(request), "schlüsseldienst")
            return await address_query_locksmith(request)
        case "abschleppdienst":
            set_intent(await caller(request), "abschleppdienst")
            return await know_plz_towing(request)
        case _:
            return await call_locksmith(request)


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

    location = extract_location(speech_result)
    logger.info("Location extracted: %s", location)
    ai_message(await caller(request), f"<Location extracted: {location}>")

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
                timeout=30,
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
                timeout=20,
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
    correct = yes_no_question(speech_result)
    user_message(await caller(request), speech_result)
    with new_response() as response:
        if correct:
            return await calculate_cost_locksmith(request)
        else:
            gather = Gather(
                input="dtmf",
                action="/parse-location-numberblock-locksmith",
                timeout=5,
            )
            message = "Bitte gib die Postleitzahl auf dem Nummernblock ein oder drücke die einz falls du deine Postleitzahl nicht kennst."       
            agent_message(await caller(request), message)
            say(gather, message)
            response.append(gather)
            gather2 = Gather(
                input="dtmf",
                action="/parse-location-numberblock-locksmith",
                timeout=20,
            )
            say(gather2, "Bitte gib die Postleitzahl erneut ein.")
            response.append(gather2)
            await fallback_no_response(response, request)   
            return send_request(request, response)


@app.api_route("/parse-location-numberblock-locksmith", methods=["GET", "POST"])
async def parse_location_numberblock_locksmith(request: Request):
    form_data = await request.form()
    plz = form_data.get("Digits", "")
    user_message(await caller(request), plz)
    if len(str(plz)) > 3:
        location_result = check_location(plz, None)
        if location_result:
            save_location(await caller(request), location_result)
            return await calculate_cost_locksmith(request)
        else:
            return await call_locksmith(request)
    else:
        return await call_locksmith(request)


async def calculate_cost_locksmith(request: Request):
    location = get_location(await caller(request))
    price, duration, provider, phone = get_price_locksmith(location)
    save_caller_contact(await caller(request), provider, phone)
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
    connection_request = yes_no_question(speech_result)
    ai_message(await caller(request), f"<Connection request: {connection_request}>")
    if connection_request:
        return await call_locksmith(request)
    else:
        return await end_call(request)


""" Towing conversation flow """


async def know_plz_towing(request: Request):
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
    plz_known = yes_no_question(speech_result)
    ai_message(await caller(request), f"<PLZ known: {plz_known}>")
    if plz_known:
        return await ask_plz_towing(request)
    else:
        return await ask_send_sms_towing(request)


async def ask_plz_towing(request: Request):
    with new_response() as response:
        gather = Gather(
            input="dtmf",
            action="/parse-plz-towing",
            timeout=30,
        )
        message = "Bitte gib die Postleitzahl deines Ortes über den Nummernblock ein."
        agent_message(await caller(request), message)
        say(gather, message)
        response.append(gather)
        gather2 = Gather(
            input="dtmf",
            action="/parse-plz-towing",
            timeout=20,
        )
        say(gather2, "Bitte gib die Postleitzahl erneut ein.")
        response.append(gather2)
        await fallback_no_response(response, request)
        return send_request(request, response)


@app.api_route("/parse-plz-towing", methods=["GET", "POST"])
async def parse_plz_towing(request: Request):
    form_data = await request.form()
    plz = form_data.get("Digits", "")
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
                timeout=30,
            )
            message = "Leider konnte ich den Ort nicht finden. Bitte gib die Postleitzahl erneut ein."
            agent_message(await caller(request), message)
            say(gather, message)
            response.append(gather)
            gather2 = Gather(
                input="dtmf",
                action="/parse-plz-towing-retry",
                timeout=20,
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
    save_caller_contact(await caller(request), provider, phone)
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
    connection_request = yes_no_question(speech_result)
    ai_message(await caller(request), f"<Connection request: {connection_request}>")
    if connection_request:
        return await call_towing_service(request)
    else:
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
    send_sms_request = yes_no_question(speech_result)
    ai_message(await caller(request), f"<Send SMS request: {send_sms_request}>")
    if send_sms_request:
        return await send_sms_towing(request)
    else:
        return await end_call(request)


async def send_sms_towing(request: Request):
    send_sms_with_link(await caller(request))
    with new_response() as response:
        message = "Wir haben soeben eine SMS mit dem Link versendet. Bitte öffne den Link und teile uns deinen Standort mit. Wir rufen dich anschließend zurück."
        agent_message(await caller(request), message)
        say(response, message)
        return send_request(request, response)


""" Call Handling """


async def call_locksmith(request: Request, with_message: bool = True):
    with new_response() as response:
        if with_message:
            message = "Ich verbinde dich jetzt mit dem Monteur. Bitte warte einen Moment."
            agent_message(await caller(request), message)
            say(response, message)
        transfer(response, await caller(request))
        transfer(response, await caller(request), "Jan")
        transfer(response, await caller(request), "Haas")
        message = "Leider sind aktuell alle Monteure im Einsatz. Bitte versuche es später erneut."
        agent_message(await caller(request), message)
        say(response, message)
        return send_request(request, response)


async def call_towing_service(request: Request, with_message: bool = True):
    with new_response() as response:
        if with_message:
            message = "Ich verbinde dich jetzt mit dem Fahrer. Bitte warte einen Moment."
            agent_message(await caller(request), message)
            say(response, message)
        transfer(response, await caller(request), "Markus")
        transfer(response, await caller(request), "Nils")
        transfer(response, await caller(request), "Ömer")
        message = "Leider sind aktuell alle Fahrer im Einsatz. Bitte versuche es später erneut."
        agent_message(await caller(request), message)
        say(response, message)
        return send_request(request, response)


async def end_call(request: Request):
    with new_response() as response:
        message = "Vielen Dank für deinen Anruf. Wir wünschen dir noch einen schönen Tag. Auf Wiederhören!"
        agent_message(await caller(request), message)
        say(response, message)
        response.hangup()
        return send_request(request, response)


@app.api_route("/status", methods=["GET", "POST"])
async def status(request: Request):
    print(await request.form())
    logger.info("Status callback from Twilio: %s", await request.form())
    return JSONResponse({"status": "ok"})
