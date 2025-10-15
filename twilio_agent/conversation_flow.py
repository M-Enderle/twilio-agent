import asyncio
import logging

import dotenv
import Levenshtein
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from twilio.twiml.voice_response import Gather

from twilio_agent.actions.location_sharing_actions import router as location_router
from twilio_agent.actions.recording_actions import router as recording_router
from twilio_agent.actions.recording_actions import start_recording
from twilio_agent.actions.redis_actions import (
    add_to_caller_queue,
    agent_message,
    ai_message,
    cleanup_call,
    clear_caller_queue,
    delete_next_caller,
    get_intent,
    get_job_info,
    get_location,
    get_transferred_to,
    google_message,
    init_new_call,
    save_job_info,
    save_location,
    set_intent,
    set_transferred_to,
    twilio_message,
    user_message,
)
from twilio_agent.actions.telegram_actions import send_telegram_notification
from twilio_agent.actions.twilio_actions import (
    caller,
    fallback_no_response,
    new_response,
    say,
    send_job_details_sms,
    send_request,
    send_sms_with_link,
    start_transfer,
)
from twilio_agent.ui import router as ui_router
from twilio_agent.utils.ai import classify_intent, extract_location, yes_no_question
from twilio_agent.utils.contacts import ContactManager
from twilio_agent.utils.location_utils import check_location, get_geocode_result
from twilio_agent.utils.pricing import get_price_locksmith, get_price_towing

dotenv.load_dotenv()

app = FastAPI()
app.include_router(location_router)
app.include_router(recording_router)
app.include_router(ui_router)


class WebSocketLogFilter(logging.Filter):
    """Filter out noisy websocket connection logs from uvicorn."""

    keywords = ("WebSocket", "connection open", "connection closed")

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not any(keyword in message for keyword in self.keywords)


# Get uvicorn logger
logger = logging.getLogger("uvicorn")

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

    if "17657888" in caller_number:
        return await greeting(request)

    logger.info("Incoming call from %s", request.headers.get("X-Twilio-Call-SID"))
    intent = get_intent(caller_number)

    previous_transferred_to = get_transferred_to(caller_number)
    with new_response() as response:
        if previous_transferred_to:

            previous_transferred_to = (
                previous_transferred_to.decode("utf-8")
                if isinstance(previous_transferred_to, bytes)
                else previous_transferred_to
            )

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
                    if caller_number != "anonymous":
                        asyncio.create_task(
                            start_recording(form_data.get("CallSid"), caller_number)
                        )
                    return await greeting(request)


async def greeting(request: Request):
    with new_response() as response:
        message = "Hallo, Schön das du bei uns anrufst. Du sprichst mit dem Assistent der Notdienststation, ich verbinde dich gleich mit dem richtigen Ansprechpartner! Wie kann ich dir helfen?"
        say(response, message)
        agent_message(await caller(request), message)

        gather = Gather(
            input="speech",
            language="de-DE",
            action="/parse-intent-1",
            speechTimeout="auto",
            timeout=15,
            enhanced=True,
            model="default",
        )
        response.append(gather)

        say(
            response,
            "Bitte beschreibe dein Anliegen damit ich dich mit dem richtigen Ansprechpartner verbinden kann.",
        )

        gather2 = Gather(
            input="speech",
            language="de-DE",
            action="/parse-intent-1",
            speechTimeout="auto",
            timeout=15,
            enhanced=True,
            model="default",
        )
        response.append(gather2)
        await fallback_no_response(response, request)
        return send_request(request, response)


@app.api_route("/parse-intent-1", methods=["GET", "POST"])
async def parse_intent_1(request: Request):
    form_data = await request.form()
    speech_result = form_data.get("SpeechResult", "")
    user_message(await caller(request), speech_result)
    try:
        classification, reasoning, duration = await asyncio.wait_for(
            asyncio.to_thread(classify_intent, speech_result), timeout=6.0
        )
    except asyncio.TimeoutError:
        ai_message(await caller(request), "<Request timed out>", 6.0)
        with new_response() as response:
            message = "Ich verbinde dich mit einem Mitarbeiter."
            say(response, message)
            agent_message(await caller(request), message)
            start_transfer(response, await caller(request))
            return send_request(request, response)
    ai_message(
        await caller(request),
        f"<Request classified as {classification}. Reasoning: {reasoning}>",
        duration,
    )
    match classification:
        case "schlüsseldienst":
            set_intent(await caller(request), "schlüsseldienst")
            return await address_query_unified(request)
        case "abschleppdienst":
            set_intent(await caller(request), "abschleppdienst")
            return await address_query_unified(request)
        case "adac" | "mitarbeiter":
            with new_response() as response:
                start_transfer(response, await caller(request))
                return send_request(request, response)
        case _:
            return await intent_not_understood(request)


async def intent_not_understood(request: Request):
    with new_response() as response:
        message = (
            "Leider konnte ich deine Anfrage nicht verstehen. Wie kann ich dir helfen?"
        )
        say(response, message)
        agent_message(await caller(request), message)

        gather = Gather(
            input="speech",
            language="de-DE",
            action="/parse-intent-2",
            speechTimeout="auto",
            timeout=15,
            enhanced=True,
            model="experimental_conversations",
        )
        response.append(gather)

        say(
            response,
            "Bitte beschreibe dein Anliegen damit ich dich mit dem richtigen Ansprechpartner verbinden kann.",
        )

        gather2 = Gather(
            input="speech",
            language="de-DE",
            action="/parse-intent-1",
            speechTimeout="auto",
            timeout=15,
            enhanced=True,
            model="experimental_conversations",
        )
        response.append(gather2)
        await fallback_no_response(response, request)
        return send_request(request, response)


@app.api_route("/parse-intent-2", methods=["GET", "POST"])
async def parse_intent_2(request: Request):
    form_data = await request.form()
    speech_result = form_data.get("SpeechResult", "")
    user_message(await caller(request), speech_result)
    try:
        classification, reasoning, duration = await asyncio.wait_for(
            asyncio.to_thread(classify_intent, speech_result), timeout=6.0
        )
    except asyncio.TimeoutError:
        ai_message(await caller(request), "<Request timed out>", 6.0)
        with new_response() as response:
            message = "Ich verbinde dich mit einem Mitarbeiter."
            say(response, message)
            agent_message(await caller(request), message)
            start_transfer(response, await caller(request))
            return send_request(request, response)
    ai_message(
        await caller(request),
        f"<Request classified as {classification}. Reasoning: {reasoning}>",
        duration,
    )
    match classification:
        case "schlüsseldienst":
            set_intent(await caller(request), "schlüsseldienst")
            return await address_query_unified(request)
        case "abschleppdienst":
            set_intent(await caller(request), "abschleppdienst")
            return await address_query_unified(request)
        case _:
            with new_response() as response:
                message = "Leider konnte ich dein Anliegen wieder nicht verstehen. Ich verbinde dich mit einem Mitarbeiter."
                agent_message(await caller(request), message)
                say(response, message)
                start_transfer(response, await caller(request))
                return send_request(request, response)


async def address_query_unified(request: Request):
    intent = get_intent(await caller(request))
    if intent == "abschleppdienst":
        await add_towing_contacts(request)
    elif intent == "schlüsseldienst":
        await add_locksmith_contacts(request)

    with new_response() as response:
        message = "Kannst du mir deine Adresse nennen? Wenn nicht, drücke bitte die 1."
        say(response, message)
        agent_message(await caller(request), message)

        gather = Gather(
            input="speech dtmf",
            language="de-DE",
            action="/parse-address-query-unified",
            speechTimeout="auto",
            timeout=15,
            enhanced=True,
            model="experimental_conversations",
            numDigits=1,
        )
        response.append(gather)

        say(
            response,
            "Bitte nenne deine Adresse oder drücke 1 wenn du sie nicht kennst.",
        )

        gather2 = Gather(
            input="speech dtmf",
            language="de-DE",
            action="/parse-address-query-unified",
            speechTimeout="auto",
            timeout=15,
            enhanced=True,
            model="experimental_conversations",
            numDigits=1,
        )
        response.append(gather2)
        await fallback_no_response(response, request)
        return send_request(request, response)


@app.api_route("/parse-address-query-unified", methods=["GET", "POST"])
async def parse_address_query_unified(request: Request):
    form_data = await request.form()
    speech_result = form_data.get("SpeechResult", "")
    digits = form_data.get("Digits", "")
    user_message(await caller(request), speech_result or digits)

    # If they pressed 1 or said something that indicates they can't name address
    if (
        digits == "1"
        or Levenshtein.distance(speech_result.lower(), "eins") <= 3
        or Levenshtein.distance(speech_result.lower(), "1") <= 2
        or not speech_result
    ):
        save_job_info(await caller(request), "Adresse unbekannt", "Ja")
        return await ask_send_sms_unified(request)

    location = get_geocode_result(speech_result)

    if not location:

        try:
            ai_result, reasoning, duration = await asyncio.wait_for(
                asyncio.to_thread(extract_location, speech_result), timeout=6.0
            )
        except asyncio.TimeoutError:
            ai_message(await caller(request), "<Request timed out>", 6.0)
            with new_response() as response:
                message = "Ich verbinde dich mit einem Mitarbeiter."
                say(response, message)
                agent_message(await caller(request), message)
                start_transfer(response, await caller(request))
                return send_request(request, response)
        ai_message(
            await caller(request),
            f"<AI location extraction: {ai_result}. Reasoning: {reasoning}>",
            duration,
        )

        # Try to parse the address they named
        location = get_geocode_result(ai_result)

    with new_response() as response:
        if location and (location.plz or location.ort):
            # Normalize location data for consistent storage
            location_dict = location._asdict()
            # Convert plz/ort to zipcode/place for compatibility
            location_dict["zipcode"] = location.plz
            location_dict["place"] = location.ort
            save_location(await caller(request), location_dict)
            place = " ".join(
                filter(
                    None,
                    [
                        " ".join(str(location.plz)) if location.plz else None,
                        location.ort,
                    ],
                )
            ).strip()  # Do not change anything here!
            google_message(
                await caller(request),
                f"Google Maps Ergebnis: {location.formatted_address} ({location.google_maps_link})",
            )
            message = f"Als Ort habe ich {place} erkannt. Ist das richtig?"
            say(response, message)
            agent_message(await caller(request), message)

            gather = Gather(
                input="speech",
                language="de-DE",
                action="/parse-location-correct-unified",
                speechTimeout="auto",
                timeout=15,
                enhanced=True,
                model="experimental_conversations",
            )
            response.append(gather)

            say(response, "Bitte bestätige, ob die Adresse korrekt ist.")

            gather2 = Gather(
                input="speech",
                language="de-DE",
                action="/parse-location-correct-unified",
                speechTimeout="auto",
                timeout=15,
                enhanced=True,
                model="experimental_conversations",
            )
            response.append(gather2)
            await fallback_no_response(response, request)
            return send_request(request, response)
        else:
            # Address not found, ask for PLZ
            google_message(
                await caller(request),
                f"Google Maps konnte die Adresse '{speech_result}' nicht eindeutig finden.",
            )
            return await ask_plz_unified(request)


async def ask_plz_unified(request: Request):
    with new_response() as response:
        message = "Bitte gib die Postleitzahl deines Ortes über den Nummernblock ein. Wenn du die Postleitzahl nicht kennst, drücke bitte die 1."

        gather = Gather(
            input="dtmf speech",
            action="/parse-plz-unified",
            timeout=5,
            numDigits=5,
            enhanced=True,
            model="experimental_conversations",
        )
        say(gather, message)
        agent_message(await caller(request), message)

        response.append(gather)

        gather2 = Gather(
            input="dtmf speech",
            action="/parse-plz-unified",
            numDigits=5,
            timeout=15,
            enhanced=True,
            model="experimental_conversations",
        )
        say(
            gather2,
            "Bitte gib die Postleitzahl ein oder drücke 1 wenn du sie nicht kennst.",
        )

        response.append(gather2)

        await fallback_no_response(response, request)
        return send_request(request, response)


@app.api_route("/parse-plz-unified", methods=["GET", "POST"])
async def parse_plz_unified(request: Request):
    form_data = await request.form()

    digits = form_data.get("Digits", "")
    speech = form_data.get("SpeechResult", "")

    if digits:
        result = str(digits)
    elif speech:
        result = str(speech).strip()
    else:
        result = "1"

    user_message(await caller(request), result)

    # Check if user pressed 1 (doesn't know PLZ)
    if result.strip() in ("1", "eins", "eine", "ein"):
        save_job_info(await caller(request), "PLZ unbekannt", "Ja")
        return await ask_send_sms_unified(request)

    # Otherwise treat as PLZ
    plz = digits
    save_job_info(await caller(request), "PLZ Tastatur", plz)
    location = check_location(plz, None)

    with new_response() as response:
        if location:
            save_location(await caller(request), location)
            link = (
                f"https://maps.google.com/?q={location['latitude']},{location['longitude']}"
                if location.get("latitude") and location.get("longitude")
                else ""
            )
            summary = f"Standort über PLZ gefunden: {location.get('place', 'Unbekannt')} {location.get('zipcode', '')}".strip()
            if link:
                summary += f" ({link})"
            google_message(await caller(request), summary)
            return await calculate_cost_unified(request)
        else:
            google_message(
                await caller(request),
                f"Keine Standortdaten für eingegebene PLZ {plz} gefunden.",
            )
            message = "Leider konnte ich den Ort nicht finden."
            say(response, message)
            agent_message(await caller(request), message)
            return await ask_send_sms_unified(request)


@app.api_route("/parse-location-correct-unified", methods=["GET", "POST"])
async def parse_location_correct_unified(request: Request):
    form_data = await request.form()
    speech_result = form_data.get("SpeechResult", "")
    try:
        correct, reasoning, duration = await asyncio.wait_for(
            asyncio.to_thread(
                yes_no_question,
                speech_result,
                "Der Kunde wurde gefragt ob die Adresse korrekt ist.",
            ),
            timeout=6.0,
        )
    except asyncio.TimeoutError:
        ai_message(await caller(request), "<Request timed out>", 6.0)
        with new_response() as response:
            message = "Ich verbinde dich mit einem Mitarbeiter."
            say(response, message)
            agent_message(await caller(request), message)
            start_transfer(response, await caller(request))
            return send_request(request, response)

    user_message(await caller(request), speech_result)
    ai_message(
        await caller(request),
        f"<Address correct: {correct}. Reasoning: {reasoning}>",
        duration,
    )

    with new_response() as response:
        if correct:
            return await calculate_cost_unified(request)
        else:
            # Address not correct, ask for PLZ
            return await ask_plz_unified(request)


async def ask_send_sms_unified(request: Request):

    # if user is anonymous, skip SMS step
    if (await caller(request)) == "anonymous":
        with new_response() as response:
            message = "Ich verbinde dich mit einem Mitarbeiter."
            say(response, message)
            agent_message(await caller(request), message)
            start_transfer(response, await caller(request))
            return send_request(request, response)

    with new_response() as response:
        message = "Wir können dir eine SMS mit einem Link zusenden, der uns deinen Standort übermittelt. Bist du damit einverstanden?"
        say(response, message)
        agent_message(await caller(request), message)

        gather = Gather(
            input="speech",
            language="de-DE",
            action="/parse-send-sms-unified",
            speechTimeout="auto",
            timeout=15,
            enhanced=True,
            model="experimental_conversations",
        )
        response.append(gather)

        say(response, "Möchtest du eine SMS mit dem Link erhalten?")

        gather2 = Gather(
            input="speech",
            language="de-DE",
            action="/parse-send-sms-unified",
            speechTimeout="auto",
            timeout=15,
            enhanced=True,
            model="experimental_conversations",
        )
        response.append(gather2)
        await fallback_no_response(response, request)
        return send_request(request, response)


@app.api_route("/parse-send-sms-unified", methods=["GET", "POST"])
async def parse_send_sms_unified(request: Request):
    form_data = await request.form()
    speech_result = form_data.get("SpeechResult", "")
    user_message(await caller(request), speech_result)
    try:
        send_sms_request, reasoning, duration = await asyncio.wait_for(
            asyncio.to_thread(
                yes_no_question,
                speech_result,
                "Der Kunde wurde gefragt ob er eine SMS mit dem Link erhalten möchte.",
            ),
            timeout=6.0,
        )
    except asyncio.TimeoutError:
        ai_message(await caller(request), "<Request timed out>", 6.0)
        with new_response() as response:
            message = "Ich verbinde dich mit einem Mitarbeiter."
            say(response, message)
            agent_message(await caller(request), message)
            start_transfer(response, await caller(request))
            return send_request(request, response)
    ai_message(
        await caller(request),
        f"<Send SMS request: {send_sms_request}. Reasoning: {reasoning}>",
        duration,
    )
    if send_sms_request:
        save_job_info(await caller(request), "SMS mit Link angefordert", "Ja")
        return await send_sms_unified(request)
    else:
        save_job_info(await caller(request), "SMS mit Link angefordert", "Nein")
        message = "Kein Problem. Ich leite dich an den Fahrer weiter."
        agent_message(await caller(request), message)
        with new_response() as response:
            say(response, message)
            start_transfer(response, await caller(request))
            return send_request(request, response)


async def send_sms_unified(request: Request):
    send_sms_with_link(await caller(request))
    save_job_info(await caller(request), "hangup_reason", "Warte auf Standort per SMS")
    save_job_info(await caller(request), "waiting_for_sms", "Ja")
    print("SMS with link sent, waiting for location...")
    with new_response() as response:
        message = "Wir haben soeben eine SMS mit dem Link versendet. Bitte öffne den Link und teile uns deinen Standort mit. Wir rufen dich anschließend zurück."
        agent_message(await caller(request), message)
        say(response, message)
        return send_request(request, response)


async def calculate_cost_unified(request: Request):
    intent = get_intent(await caller(request))
    location = get_location(await caller(request))

    if intent == "schlüsseldienst":
        try:
            longitude = float(location["longitude"])
            latitude = float(location["latitude"])
        except (KeyError, TypeError, ValueError) as exc:
            ai_message(
                await caller(request),
                f"<Locksmith pricing failed: missing coordinates ({exc})>",
            )
            with new_response() as response:
                message = "Ich verbinde dich mit einem Mitarbeiter."
                say(response, message)
                agent_message(await caller(request), message)
                start_transfer(response, await caller(request))
                return send_request(request, response)

        price, duration, provider, phone = get_price_locksmith(longitude, latitude)
        save_job_info(await caller(request), "Anbieter", provider)
        await add_locksmith_contacts(request)

    else:  # abschleppdienst
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
        message = f"Die Kosten betragen {price} Euro und die Wartezeit beträgt {duration} Minuten. Möchtest du jetzt verbunden werden?"
        say(response, message)
        agent_message(await caller(request), message)

        gather = Gather(
            input="speech",
            language="de-DE",
            action="/parse-connection-request-unified",
            speechTimeout="auto",
            timeout=15,
            enhanced=True,
            model="experimental_conversations",
        )
        response.append(gather)

        say(response, "Bitte sage ja oder nein.")

        gather2 = Gather(
            input="speech",
            language="de-DE",
            action="/parse-connection-request-unified",
            speechTimeout="auto",
            timeout=15,
            enhanced=True,
            model="experimental_conversations",
        )
        response.append(gather2)
        await fallback_no_response(response, request)
        return send_request(request, response)


@app.api_route("/parse-connection-request-unified", methods=["GET", "POST"])
async def parse_connection_request_unified(request: Request):
    form_data = await request.form()
    speech_result = form_data.get("SpeechResult", "")
    user_message(await caller(request), speech_result)
    try:
        connection_request, reasoning, duration = await asyncio.wait_for(
            asyncio.to_thread(
                yes_no_question,
                speech_result,
                "Der Kunde wurde gefragt ob er verbunden werden möchte.",
            ),
            timeout=6.0,
        )
    except asyncio.TimeoutError:
        ai_message(await caller(request), "<Request timed out>", 6.0)
        with new_response() as response:
            message = "Ich verbinde dich mit einem Mitarbeiter."
            say(response, message)
            agent_message(await caller(request), message)
            start_transfer(response, await caller(request))
            return send_request(request, response)
    ai_message(
        await caller(request),
        f"<Connection request: {connection_request}. Reasoning: {reasoning}>",
        duration,
    )
    if connection_request:
        save_job_info(await caller(request), "Weiterleitung angefordert", "Ja")
        with new_response() as response:
            start_transfer(response, await caller(request))
            return send_request(request, response)
    else:
        save_job_info(await caller(request), "Weiterleitung angefordert", "Nein")
        return await end_call(request)


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
    add_to_caller_queue(await caller(request), "Andi")
    add_to_caller_queue(await caller(request), "Nils")
    add_to_caller_queue(await caller(request), "Oemer")
    save_job_info(await caller(request), "Anruf Warteschlange", "Andi, Nils, Ömer")


async def end_call(request: Request, with_message: bool = True):
    with new_response() as response:
        if with_message:
            message = (
                "Vielen Dank für deinen Anruf. Wir wünschen dir noch einen schönen Tag."
            )
            agent_message(await caller(request), message)
            say(response, message)
        save_job_info(
            await caller(request), "hangup_reason", "Agent hat das Gespräch beendet"
        )
        response.hangup()
        return send_request(request, response)


@app.api_route("/status", methods=["GET", "POST"])
async def status(request: Request):
    form = await request.form()
    logger.info("Call status: %s", dict(form))

    if form.get("CallStatus") == "completed":
        save_job_info(await caller(request), "Live", "Nein")

        if not get_job_info(await caller(request), "hangup_reason"):
            save_job_info(
                await caller(request), "hangup_reason", "Anruf durch Kunde beendet"
            )

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
                message = "Leider sind alle unsere Mitarbeiter im Gespräch. Bitte rufe später erneut an."
                agent_message(await caller(request), message)
                say(response, message)
                save_job_info(
                    await caller(request),
                    "hangup_reason",
                    "Agent hat das Gespräch beendet",
                )
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
        save_job_info(
            await caller(request), "hangup_reason", "Erfolgreich weitergeleitet"
        )
        return send_request(request, response)
