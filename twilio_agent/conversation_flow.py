import logging

from fastapi.responses import JSONResponse
from twilio_agent.utils.utils import which_service, direct_transfer, call_info
from fastapi import APIRouter, Request
from twilio_agent.actions.redis_actions import get_job_info, init_new_call, get_transferred_to, save_job_info, clear_caller_queue, add_to_caller_queue
from twilio_agent.settings import settings
from twilio_agent.actions.telegram_actions import send_simple_notification, send_telegram_notification
import asyncio
from twilio_agent.actions.twilio_actions import new_response, send_request, say, start_transfer
from twilio.twiml.voice_response import Dial, Number

from twilio_agent.flow.entry import greet
from twilio_agent.flow.address import ask_address_handler, process_address_handler, address_processed_handler, confirm_address_handler
from twilio_agent.flow.plz import ask_plz_handler, process_plz_handler, ask_send_sms_handler, process_sms_offer_handler
from twilio_agent.flow.pricing import start_pricing_handler, parse_connection_request_handler
from twilio_agent.flow.transfer import parse_transfer_call_handler
from twilio_agent.actions.recording_actions import start_recording

logger = logging.getLogger("ConversationFlow")

router = APIRouter()

# >> 1. Call starts here <<
@router.api_route("/incoming-call", methods=["GET", "POST"])
async def incoming_call(request: Request):
    caller_number, called_number, form_data = await call_info(request)

    # check which service the call belongs to based on the called number
    service = which_service(called_number)
    logger.info(f"Called number: {called_number} → Determined service: {service}")
    assert service, f"Could not determine service for called number {called_number}"

    # Check if the user called before
    previous_transfer = get_transferred_to(caller_number)
    if previous_transfer and not "12905" in caller_number and not "888987" in caller_number:
        prev_phone, prev_name = previous_transfer
        logger.info(f"Caller {caller_number} was previously transferred to {prev_name} ({prev_phone}). Transferring directly.")

        # Initialize call so it appears in history
        init_new_call(caller_number, service)
        save_job_info(caller_number, "Wiederholungsanruf", "Ja")

        # Start recording
        call_sid = form_data.get("CallSid")
        if call_sid and caller_number != "anonymous":
            asyncio.create_task(start_recording(call_sid, caller_number))

        # Send Telegram notification
        asyncio.create_task(send_telegram_notification(caller_number, service))

        # Set up queue with the previous contact
        clear_caller_queue(caller_number)
        contact_name = prev_name or "Vorheriger Kontakt"
        add_to_caller_queue(caller_number, contact_name, prev_phone)
        save_job_info(caller_number, "Dienstleister", contact_name)

        response = new_response()
        say(response, settings.service(service).announcements.transfer_message)
        start_transfer(response, caller_number)
        return send_request(request, response)

    # check for direct transfer
    if direct_transfer(service) and not "12905" in caller_number and not "888987" in caller_number:
        logger.info(f"Forwarding call to {settings.service(service).direct_forwarding.forward_phone}")
        asyncio.create_task(send_simple_notification(caller_number, service))

        response = new_response()
        dial = Dial(callerId=settings.service(service).phone_number)
        dial.append(Number(settings.service(service).direct_forwarding.forward_phone))
        response.append(dial)
        return send_request(request, response)

    # If not direct transfer init a new call
    init_new_call(caller_number, service)
    logging.info(f"Incoming call from {caller_number} to {called_number} associated with service: {service}")

    # Start call recording (asynchronously)
    if caller_number != "anonymous":
        call_sid = form_data.get("CallSid")
        if call_sid:
            asyncio.create_task(start_recording(call_sid, caller_number))
            logger.info(f"Started recording for call {call_sid}")

    # Send live notification
    live_url = await send_telegram_notification(caller_number, service)
    logger.info("Telegram live UI URL: %s", live_url)

    # Greet the caller
    return await greet(service, request)

# >> 2. Ask the user for their address <<
@router.api_route("/ask-adress", methods=["GET", "POST"])
async def ask_address(request: Request):
    return await ask_address_handler(request)

# >> 2.1 Process the address the user provided <<
@router.api_route("/process-address", methods=["GET", "POST"])
async def process_address(request: Request):
    return await process_address_handler(request)

# >> 2.2 Processing of the adress done
@router.api_route("/address-processed", methods=["GET", "POST"])
async def address_processed(request: Request): 
    return await address_processed_handler(request)

# >> 2.3 Parse confirmation of the address <<
@router.api_route("/confirm-address", methods=["GET", "POST"])
async def confirm_address(request: Request):
    return await confirm_address_handler(request)

# >> 3. PLZ fallback flow <<
@router.api_route("/ask-plz", methods=["GET", "POST"])
async def ask_plz(request: Request):
    return await ask_plz_handler(request)

@router.api_route("/process-plz", methods=["GET", "POST"])
async def process_plz(request: Request):
    return await process_plz_handler(request)

# >> 4. SMS location sharing flow <<
@router.api_route("/ask-send-sms", methods=["GET", "POST"])
async def ask_send_sms(request: Request):
    return await ask_send_sms_handler(request)

@router.api_route("/process-sms-offer", methods=["GET", "POST"])
async def process_sms_offer(request: Request):
    return await process_sms_offer_handler(request)

# >> 5. Pricing and connection flow <<
@router.api_route("/start-pricing", methods=["GET", "POST"])
async def start_pricing(request: Request):
    return await start_pricing_handler(request)

@router.api_route("/parse-connection-request", methods=["GET", "POST"])
async def parse_connection_request(request: Request):
    return await parse_connection_request_handler(request)

# >> 6. Transfer callback flow <<
@router.api_route("/parse-transfer-call/{name}/{phone}", methods=["GET", "POST"])
async def parse_transfer_call(request: Request, name: str, phone: str):
    return await parse_transfer_call_handler(request, name, phone)

# >> Call Status Change <<
@router.api_route("/status-change", methods=["GET", "POST"])
async def status_change(request: Request):

    caller_number, called_number, form_data = await call_info(request)
    call_status = form_data.get("CallStatus")
    logger.info(f"Call status changed for {caller_number}: {call_status}")

    if form_data.get("CallStatus") == "completed":
        save_job_info(caller_number, "Live", "Nein")

        if not get_job_info(caller_number, "hangup_reason"):
            save_job_info(caller_number, "hangup_reason", "Anruf durch Kunde beendet")

        # Clean up the transfer queue when call ends
        clear_caller_queue(caller_number)

    return JSONResponse(content={"status": "ok"})