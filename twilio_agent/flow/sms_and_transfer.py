"""SMS fallback and cost confirmation steps before the handover."""

from __future__ import annotations

import asyncio
import logging

import num2words
from fastapi import APIRouter, Request
from twilio.twiml.voice_response import Gather

from twilio_agent.actions.redis_actions import (ai_message, get_intent,
                                                get_location, save_job_info,
                                                user_message)
from twilio_agent.actions.twilio_actions import (new_response, say,
                                                 send_request,
                                                 send_sms_with_link,
                                                 start_transfer)
from twilio_agent.flow.management import (add_locksmith_contacts,
                                          add_towing_contacts, end_call)
from twilio_agent.flow.shared import (get_caller_number, narrate,
                                      send_twilio_response,
                                      transfer_with_message)
from twilio_agent.utils.ai import yes_no_question
from twilio_agent.utils.pricing import get_price_locksmith, get_price_towing

logger = logging.getLogger(__name__)

router = APIRouter()


async def ask_send_sms_unified(request: Request):
    """Offer an SMS link as a fallback to collect the location."""
    caller_number = await get_caller_number(request)

    if caller_number == "anonymous":
        return await transfer_with_message(request)

    with new_response() as response:
        message = "Wir können dir eine SMS mit einem Link zusenden, der uns deinen Standort übermittelt. Möchtest du das?"
        narrate(response, caller_number, message)

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

        return await send_twilio_response(request, response)


@router.api_route("/parse-send-sms-unified", methods=["GET", "POST"])
async def parse_send_sms_unified(request: Request):
    """Interpret the caller's answer to the SMS fallback question."""
    caller_number = await get_caller_number(request)
    form_data = await request.form()
    speech_result = form_data.get("SpeechResult", "")
    user_message(caller_number, speech_result)

    try:
        send_sms_request, reasoning, duration, model_source = await asyncio.wait_for(
            yes_no_question(
                speech_result,
                "Der Kunde wurde gefragt ob er eine SMS mit dem Link erhalten möchte.",
            ),
            timeout=6.0,
        )
    except asyncio.TimeoutError:
        ai_message(caller_number, "<Request timed out>", 6.0)
        return await transfer_with_message(request)

    ai_message(
        caller_number,
        f"<Send SMS request: {send_sms_request}. Reasoning: {reasoning}>",
        duration,
        model_source,
    )

    if send_sms_request:
        save_job_info(caller_number, "SMS mit Link angefordert", "Ja")
        return await send_sms_unified(request)

    save_job_info(caller_number, "SMS mit Link angefordert", "Nein")
    with new_response() as response:
        message = "Kein Problem. Ich leite dich an den Fahrer weiter."
        narrate(response, caller_number, message)
        start_transfer(response, caller_number)
        return send_request(request, response)


async def send_sms_unified(request: Request):
    """Trigger the SMS workflow and end the call while waiting for input."""
    caller_number = await get_caller_number(request)

    send_sms_with_link(caller_number)
    save_job_info(caller_number, "hangup_reason", "Warte auf Standort per SMS")
    save_job_info(caller_number, "waiting_for_sms", "Ja")
    logger.info("SMS with link sent, waiting for location...")

    with new_response() as response:
        message = "Wir haben soeben eine SMS mit dem Link versendet. Bitte öffne den Link und teile uns deinen Standort mit. Wir rufen dich anschließend zurück."
        narrate(response, caller_number, message)
        return send_request(request, response)


async def calculate_cost_unified(request: Request):
    """Quote the estimated price and wait time based on the caller's location."""
    caller_number = await get_caller_number(request)
    intent = get_intent(caller_number, True)
    location = get_location(caller_number)

    try:
        longitude = float(location["longitude"])
        latitude = float(location["latitude"])
    except (KeyError, TypeError, ValueError) as exc:
        ai_message(
            caller_number,
            f"<Locksmith pricing failed: missing coordinates ({exc})>",
        )
        return await ask_send_sms_unified(request)

    try:
        if intent == "schlüsseldienst":
            price, duration, provider, phone = get_price_locksmith(longitude, latitude)
            save_job_info(caller_number, "Anbieter", provider)
            await add_locksmith_contacts(request)
        else:
            price, duration, provider, phone = get_price_towing(longitude, latitude)
            save_job_info(caller_number, "Anbieter", provider)
            await add_towing_contacts(request)
    except Exception as exc:
        ai_message(
            caller_number,
            f"<Pricing failed for intent '{intent}': {exc}>",
        )
        return await ask_send_sms_unified(request)

    german_keys = {
        "price": "Preis",
        "duration": "Wartezeit",
        "provider": "Anbieter",
        "phone": "Telefon",
    }
    for key in ["price", "duration", "provider", "phone"]:
        save_job_info(caller_number, german_keys[key], locals()[key])

    hours, minutes = divmod(duration, 60)
    hours_words = num2words.num2words(hours, lang="de")
    minutes_words = num2words.num2words(minutes, lang="de")
    duration_str = (
        f"{hours_words} Stunden und {minutes_words} Minuten"
        if hours > 0
        else f"{minutes_words} Minuten"
    )

    with new_response() as response:
        price_words = num2words.num2words(price, lang="de")
        message = f"Die Kosten betragen {price_words} Euro und die Wartezeit beträgt {duration_str}. Möchtest du jetzt verbunden werden?"
        narrate(response, caller_number, message)
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

        return await send_twilio_response(request, response)


@router.api_route("/parse-connection-request-unified", methods=["GET", "POST"])
async def parse_connection_request_unified(request: Request):
    """Check whether the caller wants to be connected right away."""
    caller_number = await get_caller_number(request)
    from twilio_agent.actions.redis_actions import user_message

    form_data = await request.form()
    speech_result = form_data.get("SpeechResult", "")
    user_message(caller_number, speech_result)

    try:
        connection_request, reasoning, duration, model_source = await asyncio.wait_for(
            yes_no_question(
                speech_result,
                "Der Kunde wurde gefragt ob er verbunden werden möchte.",
            ),
            timeout=6.0,
        )
    except asyncio.TimeoutError:
        ai_message(caller_number, "<Request timed out>", 6.0)
        return await transfer_with_message(request)

    ai_message(
        caller_number,
        f"<Connection request: {connection_request}. Reasoning: {reasoning}>",
        duration,
        model_source,
    )

    if connection_request:
        save_job_info(caller_number, "Weiterleitung angefordert", "Ja")
        with new_response() as response:
            start_transfer(response, caller_number)
            return send_request(request, response)

    save_job_info(caller_number, "Weiterleitung angefordert", "Nein")
    return await end_call(request)
