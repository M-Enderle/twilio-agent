"""Address collection and confirmation steps of the call flow."""

import asyncio
import logging
import re
import os
import threading
from num2words import num2words

from fastapi import APIRouter, Request
from twilio.twiml.voice_response import Gather, Record, Redirect

from twilio_agent.actions.redis_actions import (
    ai_message,
    get_intent,
    google_message,
    redis as redis_client,
    save_job_info,
    save_location,
    user_message,
)
from twilio_agent.actions.twilio_actions import new_response, say
from twilio_agent.flow.management import (add_locksmith_contacts,
                                          add_towing_contacts)
from twilio_agent.flow.shared import (get_caller_number, narrate,
                                      send_twilio_response,
                                      transfer_with_message)
from twilio_agent.flow.sms_and_transfer import (ask_send_sms_unified,
                                                calculate_cost_unified)
from twilio_agent.utils.ai import process_location, yes_no_question
from twilio_agent.utils.eleven import transcribe_speech
from twilio_agent.utils.location_utils import get_geocode_result

logger = logging.getLogger(__name__)

router = APIRouter()
server_url = os.environ["SERVER_URL"]

TRANSCRIPTION_KEY_SUFFIX = "address_transcription"
TRANSCRIPTION_RESULT_TTL = 120
TRANSCRIPTION_POLL_INTERVAL = 0.2
TRANSCRIPTION_POLL_TIMEOUT = 8.0
TRANSCRIPTION_ERROR_VALUE = "__TRANSCRIPTION_ERROR__"
TWILIO_RECORDING_ACCOUNT = "AC57026df7ad4ab96c1b6387a4bf2221a4"
CITY_ADDON_KEY_SUFFIX = "address_city_addon"
CITY_ADDON_TTL = 300


def _build_recording_url(recording_id: str) -> str:
    return (
        f"https://api.twilio.com/2010-04-01/Accounts/"
        f"{TWILIO_RECORDING_ACCOUNT}/Recordings/{recording_id}"
    )


def _transcription_key(caller_number: str) -> str:
    return f"notdienststation:anrufe:{caller_number}:{TRANSCRIPTION_KEY_SUFFIX}"


async def address_query_unified(request: Request):
    """Ask the caller to share their location once the intent is known."""
    caller_number = await get_caller_number(request)
    intent = get_intent(caller_number, True)

    if intent == "abschleppdienst":
        await add_towing_contacts(request)
    elif intent == "schlüsseldienst":
        await add_locksmith_contacts(request)

    with new_response() as response:
        narrate(response, caller_number, "Nenne mir bitte deine Adresse mit Straße, Hausnummer und Wohnort.")
        response.append(
            Record(
                action="/parse-address-recording/",
                timeout=5,
                playBeep=False,
                maxLength=10,
            )
        )
        return await send_twilio_response(request, response)
    

@router.api_route("/parse-address-recording/", methods=["GET", "POST"])
async def parse_address_recording(request: Request):
    """Transcribe the recorded address and resolve it via Google Maps."""
    caller_number = await get_caller_number(request)
    form_data = await request.form()
    recording_url = form_data.get("RecordingUrl", "")
    if not recording_url:
        return await ask_plz_unified(request)
    recording_id = recording_url.rstrip("/").split("/")[-1]
    if caller_number and recording_id:
        def worker() -> None:
            cache_value = TRANSCRIPTION_ERROR_VALUE
            try:
                speech_result, _ = transcribe_speech(_build_recording_url(recording_id))
                cache_value = speech_result or ""
            except Exception:  # noqa: BLE001 - logging and falling back downstream
                logger.exception("Failed to transcribe address for %s", caller_number)
            try:
                redis_client.set(
                    _transcription_key(caller_number),
                    cache_value,
                    ex=TRANSCRIPTION_RESULT_TTL,
                )
            except Exception:  # noqa: BLE001 - fallback handled later
                logger.exception(
                    "Failed to cache address transcription for %s", caller_number
                )

        thread_name = f"addr-transcribe-{caller_number.replace('+', 'p')}"
        threading.Thread(target=worker, name=thread_name, daemon=True).start()
    with new_response() as response:
        narrate(response, caller_number, "Einen Moment, ich prüfe deine Eingabe.")
        redirect = Redirect(f"{server_url}/parse-address-recording-2/{recording_id}")
        response.append(redirect)
        return await send_twilio_response(request, response)


@router.api_route("/parse-address-recording-2/{recording_id}", methods=["GET", "POST"])
async def parse_address_recording_2(request: Request, recording_id: str):
    """Transcribe the recorded address and resolve it via Google Maps."""
    caller_number = await get_caller_number(request)
    if not recording_id:
        save_job_info(caller_number, "Adresse unbekannt", "Ja")
        return await ask_send_sms_unified(request)

    if not caller_number:
        speech_result = None
    else:
        key = _transcription_key(caller_number)
        elapsed = 0.0
        speech_result = None
        while elapsed < TRANSCRIPTION_POLL_TIMEOUT:
            try:
                cached = redis_client.get(key)
            except Exception:  # noqa: BLE001 - break to fall back to direct call
                logger.exception(
                    "Failed to read cached address transcription for %s", caller_number
                )
                break
            if cached is not None:
                try:
                    redis_client.delete(key)
                except Exception:  # noqa: BLE001 - non-critical clean-up failure
                    logger.exception(
                        "Failed to clear cached address transcription for %s",
                        caller_number,
                    )
                decoded = cached.decode("utf-8") if isinstance(cached, bytes) else cached
                if decoded == TRANSCRIPTION_ERROR_VALUE:
                    speech_result = None
                else:
                    speech_result = decoded
                break
            await asyncio.sleep(TRANSCRIPTION_POLL_INTERVAL)
            elapsed += TRANSCRIPTION_POLL_INTERVAL
        if speech_result is None:
            try:
                redis_client.delete(key)
            except Exception:  # noqa: BLE001 - non-critical clean-up failure
                logger.exception(
                    "Failed to clear stale address transcription key for %s", caller_number
                )
    if speech_result is None:
        speech_result, _ = transcribe_speech(_build_recording_url(recording_id))
    speech_result = (speech_result or "").strip()

    user_message(caller_number, speech_result)

    try:
        contains_loc, contains_city_bool, knows_adress, extracted_address, duration, model_source = await asyncio.wait_for(
            process_location(speech_result), timeout=6.0
        )
    except asyncio.TimeoutError:
        ai_message(caller_number, "<Request timed out>", 6.0)
        return await transfer_with_message(request)
    
    if knows_adress is not None and not knows_adress:
        ai_message(
            caller_number,
            f"<Location not known by caller: knows_location={knows_adress}>",
            duration,
            model_source,
        )
        return await ask_send_sms_unified(request)

    if not contains_loc or not contains_city_bool:
        ai_message(
            caller_number,
            f"<Location extraction failed: contains_location={contains_loc}, contains_city={contains_city_bool}. Extracted address: {extracted_address}>",
            duration,
            model_source,
        )
        return await ask_plz_unified(request)
    
    ai_message(
        caller_number,
        f"<Location extracted: {extracted_address}>",
        duration,
        model_source,
    )

    try:
        location = get_geocode_result(extracted_address)
    except Exception as exc:
        logger.error("Error getting geocode result: %s", exc)
        location = None

    if not location or (not location.plz and not location.ort):
        google_message(
            caller_number,
            f"Google Maps konnte die Adresse '{extracted_address}' nicht eindeutig finden.",
        )
        return await ask_plz_unified(request)
    
    parsed_location = extracted_address
    save_job_info(caller_number, "Adresse erkannt", parsed_location)
    google_message(caller_number, f"Erkannte Adresse: {parsed_location}")

    if not parsed_location:
        return await ask_plz_unified(request)

    location = get_geocode_result(parsed_location)
    if location and (location.plz or location.ort):
        location_dict = location._asdict()
        location_dict["zipcode"] = location.plz
        location_dict["place"] = location.ort
        save_location(caller_number, location_dict)

        google_message(
            caller_number,
            f"Google Maps Ergebnis: {location.formatted_address} ({location.google_maps_link})",
        )

        place_phrase = " ".join(
            filter(None, [" ".join(num2words(int(d), lang="de") for d in str(location.plz or "") if d.isdigit()).strip(), location.ort])
        ).strip() or location.formatted_address

        with new_response() as response:
            narrate(
                response,
                caller_number,
                f"Als Ort habe ich {place_phrase} erkannt. Ist das richtig?",
            )
            gather_kwargs = dict(
                input="speech",
                language="de-DE",
                action="/parse-location-correct-unified",
                speechTimeout="auto",
                timeout=5,
                enhanced=True,
                model="experimental_conversations",
            )
            gather = Gather(**gather_kwargs)
            response.append(gather)

            say(response, "Bitte bestätige mit ja oder nein, ob die Adresse korrekt ist.")
            gather2 = Gather(**gather_kwargs)
            response.append(gather2)
            
            return await send_twilio_response(request, response)

    google_message(
        caller_number,
        f"Google Maps konnte die Adresse '{parsed_location}' nicht eindeutig finden.",
    )
    return await ask_plz_unified(request)


async def ask_plz_unified(request: Request):
    """Prompt the caller to share their postal code via DTMF or speech."""
    caller_number = await get_caller_number(request)

    with new_response() as response:
        message = "Bitte gib die Postleitzahl deines Ortes über den Nummernblock ein."

        gather = Gather(
            input="dtmf speech",
            action="/parse-plz-unified",
            timeout=10,
            numDigits=5,
            model="experimental_utterances",
            language="de-DE",
            speechTimeout="auto",
        )
        narrate(response, caller_number, message)
        response.append(gather)

    return await send_twilio_response(request, response)


@router.api_route("/parse-plz-unified", methods=["GET", "POST"])
async def parse_plz_unified(request: Request):
    """Handle the postal-code input and resolve it to a location."""
    caller_number = await get_caller_number(request)
    form_data = await request.form()
    digits = form_data.get("Digits", "")
    speech = form_data.get("SpeechResult", "")

    if digits:
        result = str(digits)
        logger.info("Digits: %s", result)
    elif speech:
        result = str(speech)
        re_identifier = r"(?<=\b\d\b)\s+(?=\b\d\b)"
        result = re.sub(re_identifier, "", result)
        logger.info("Speech: %s", result)
    else:
        result = "1"

    user_message(caller_number, result)
    plz = result
    save_job_info(caller_number, "PLZ Tastatur", plz)

    try:
        location = get_geocode_result(plz)
    except Exception as exc:
        logger.error("Error getting geocode result: %s", exc)
        location = None

    if location and (location.plz or location.ort):
        location_dict = location._asdict()
        location_dict["zipcode"] = location.plz
        location_dict["place"] = location.ort
        save_location(caller_number, location_dict)
        place = " ".join(
            filter(
                None,
                [
                    " ".join(str(location.plz)) if location.plz else None,
                    location.ort,
                ],
            )
        ).strip()
        google_message(
            caller_number,
            f"Standort über PLZ gefunden: {location.formatted_address} ({location.google_maps_link})",
        )
        return await calculate_cost_unified(request)

    google_message(
        caller_number,
        f"Keine Standortdaten für eingegebene PLZ {plz} gefunden.",
    )
    return await ask_send_sms_unified(request)


@router.api_route("/parse-location-correct-unified", methods=["GET", "POST"])
async def parse_location_correct_unified(request: Request):
    """Check whether the recognized address was correct."""
    caller_number = await get_caller_number(request)
    form_data = await request.form()
    speech_result = form_data.get("SpeechResult", "")
    user_message(caller_number, speech_result)

    try:
        correct, reasoning, duration, model_source = await asyncio.wait_for(
            yes_no_question(
                speech_result,
                "Der Kunde wurde gefragt ob die Adresse korrekt ist.",
            ),
            timeout=6.0,
        )
    except asyncio.TimeoutError:
        ai_message(caller_number, "<Request timed out>", 6.0)
        return await transfer_with_message(request)

    ai_message(
        caller_number,
        f"<Address correct: {correct}. Reasoning: {reasoning}>",
        duration,
        model_source,
    )

    if correct:
        return await calculate_cost_unified(request)

    return await ask_plz_unified(request)
