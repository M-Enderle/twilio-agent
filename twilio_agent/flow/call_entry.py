"""Entry points into the automated call flow (greeting and intent parsing)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, Request
from twilio.twiml.voice_response import Gather
import pytz

from twilio_agent.actions.recording_actions import start_recording
from twilio_agent.actions.redis_actions import (add_to_caller_queue,
                                                ai_message, clear_caller_queue,
                                                get_intent, get_transferred_to,
                                                init_new_call, save_job_info,
                                                set_intent, user_message)
from twilio_agent.actions.telegram_actions import send_telegram_notification, send_simple_notification
from twilio_agent.actions.twilio_actions import (fallback_no_response,
                                                 new_response, say,
                                                 send_request, start_transfer)
from twilio.twiml.voice_response import Dial, Number
from twilio_agent.flow.address import address_query_unified
from twilio_agent.flow.management import (add_locksmith_contacts,
                                          add_default_contacts,
                                          add_towing_contacts)
from twilio_agent.flow.shared import (get_caller_number, narrate,
                                      send_twilio_response,
                                      transfer_with_message)
from twilio_agent.utils.ai import classify_intent
from twilio_agent.utils.settings import SettingsManager

logger = logging.getLogger(__name__)

router = APIRouter()


@router.api_route("/incoming-call", methods=["GET", "POST"])
async def incoming_call(request: Request):
    """Initial endpoint that processes every inbound call."""
    caller_number = await get_caller_number(request)
    form_data = await request.form()

    # Check direct forwarding settings
    settings_manager = SettingsManager()
    direct_forwarding = settings_manager.get_direct_forwarding()
    vacation = settings_manager.get_vacation_mode()

    if direct_forwarding.get("active") and direct_forwarding.get("forward_phone") and not vacation.get("active"):
        berlin_tz = pytz.timezone('Europe/Berlin')
        current_time = datetime.now(berlin_tz)
        current_hour = current_time.hour + current_time.minute / 60

        start_hour = direct_forwarding.get("start_hour", 0)
        end_hour = direct_forwarding.get("end_hour", 6)

        # Check if current time is within forwarding window
        if start_hour <= current_hour < end_hour:
            asyncio.create_task(send_simple_notification(caller_number))

            with new_response() as response:
                dial = Dial(callerId="+491604996655")
                dial.append(Number(direct_forwarding["forward_phone"]))
                response.append(dial)
                return send_request(request, response)

    init_new_call(caller_number)

    live_url = await send_telegram_notification(caller_number)
    logger.info("Telegram live UI URL: %s", live_url)

    # Special debugging numbers
    if (
        "17657888" in caller_number
        or "1601212905" in caller_number
        or "13479191091" in caller_number
    ):
        await add_default_contacts(request)
        return await greeting(request)

    clear_caller_queue(caller_number)

    logger.info("Incoming call from %s", request.headers.get("X-Twilio-Call-SID"))
    intent = get_intent(caller_number, True)

    previous_transferred_to = get_transferred_to(caller_number)
    if previous_transferred_to:
        transferred_to = (
            previous_transferred_to.decode("utf-8")
            if isinstance(previous_transferred_to, bytes)
            else previous_transferred_to
        )
        save_job_info(caller_number, "Zuvor Angerufen", "Ja")
        save_job_info(caller_number, "Zuvor weitergeileitet an", transferred_to)
        with new_response() as response:
            add_to_caller_queue(caller_number, transferred_to)
            start_transfer(response, caller_number)
            return send_request(request, response)

    if intent:
        save_job_info(caller_number, "Zuvor Angerufen", "Ja")
        save_job_info(caller_number, "Vorheriges Anliegen", intent)

    await add_default_contacts(request)

    if intent == "schlüsseldienst":
        with new_response() as response:
            start_transfer(response, caller_number)
            return send_request(request, response)

    if intent == "abschleppdienst":
        await add_towing_contacts(request)
        with new_response() as response:
            start_transfer(response, caller_number)
            return send_request(request, response)

    if caller_number != "anonymous":
        asyncio.create_task(start_recording(form_data.get("CallSid"), caller_number))

    return await greeting(request)


async def greeting(request: Request):
    """Welcome message that invites the caller to describe the problem."""
    caller_number = await get_caller_number(request)

    with new_response() as response:
        message = "Hallo, hier ist die Notdienststation. Wie kann ich dir helfen?"
        narrate(response, caller_number, message)

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

        return await send_twilio_response(request, response)


@router.api_route("/parse-intent-1", methods=["GET", "POST"])
async def parse_intent_1(request: Request):
    """First attempt to classify the caller's intent."""
    caller_number = await get_caller_number(request)
    form_data = await request.form()
    speech_result = form_data.get("SpeechResult", "")
    user_message(caller_number, speech_result)

    try:
        classification, reasoning, duration, model_source = await asyncio.wait_for(
            classify_intent(speech_result), timeout=6.0
        )
    except asyncio.TimeoutError:
        ai_message(caller_number, "<Request timed out>", 6.0)
        return await transfer_with_message(request)

    ai_message(
        caller_number,
        f"<Request classified as {classification}. Reasoning: {reasoning}>",
        duration,
        model_source,
    )

    if classification == "schlüsseldienst":
        set_intent(caller_number, "schlüsseldienst")
        await add_locksmith_contacts(request)
        return await address_query_unified(request)
    
    if classification == "abschleppdienst":
        set_intent(caller_number, "abschleppdienst")
        await add_towing_contacts(request)
        return await address_query_unified(request)
    
    if classification in {"adac", "mitarbeiter"}:
        return await transfer_with_message(request)

    return await intent_not_understood(request)


async def intent_not_understood(request: Request):
    """Fallback when intent classification was inconclusive."""
    caller_number = await get_caller_number(request)
    with new_response() as response:
        message = (
            "Leider konnte ich deine Anfrage nicht verstehen. Wie kann ich dir helfen?"
        )
        narrate(response, caller_number, message)

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
        return await send_twilio_response(request, response)


@router.api_route("/parse-intent-2", methods=["GET", "POST"])
async def parse_intent_2(request: Request):
    """Second attempt to classify the caller's intent after a fallback."""
    caller_number = await get_caller_number(request)
    form_data = await request.form()
    speech_result = form_data.get("SpeechResult", "")
    user_message(caller_number, speech_result)

    try:
        classification, reasoning, duration, model_source = await asyncio.wait_for(
            classify_intent(speech_result), timeout=6.0
        )
    except asyncio.TimeoutError:
        ai_message(caller_number, "<Request timed out>", 6.0)
        return await transfer_with_message(request)

    ai_message(
        caller_number,
        f"<Request classified as {classification}. Reasoning: {reasoning}>",
        duration,
        model_source,
    )

    if classification == "schlüsseldienst":
        set_intent(caller_number, "schlüsseldienst")
        await add_locksmith_contacts(request)
        return await address_query_unified(request)
    
    if classification == "abschleppdienst":
        set_intent(caller_number, "abschleppdienst")
        await add_towing_contacts(request)
        return await address_query_unified(request)

    with new_response() as response:
        message = "Leider konnte ich dein Anliegen wieder nicht verstehen. Ich verbinde dich mit einem Mitarbeiter."
        narrate(response, caller_number, message)
        start_transfer(response, caller_number)
        return send_request(request, response)
