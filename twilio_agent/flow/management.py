"""Contact queue management and transfer related endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from twilio_agent.actions.redis_actions import (add_to_caller_queue,
                                                clear_caller_queue,
                                                delete_next_caller,
                                                get_job_info, save_job_info,
                                                set_transferred_to,
                                                twilio_message)
from twilio_agent.actions.twilio_actions import (new_response,
                                                 send_job_details_sms,
                                                 send_request, start_transfer)
from twilio_agent.flow.shared import get_caller_number, narrate
from twilio_agent.utils.contacts import ContactManager

logger = logging.getLogger(__name__)

router = APIRouter()


async def add_locksmith_contacts(request: Request):
    """Populate the transfer queue with locksmith contacts."""
    caller_number = await get_caller_number(request)
    clear_caller_queue(caller_number)
    first_contact = get_job_info(caller_number, "Anbieter") or "Andi"
    add_to_caller_queue(caller_number, first_contact)

    if first_contact.lower() not in ["tiberius", "marcel"]:
        add_to_caller_queue(caller_number, "Haas")
        add_to_caller_queue(caller_number, "Wassermann")

    cm = ContactManager()
    for contact in cm.get_contacts_for_category("locksmith"):
        name = contact.get("name", "")
        if name.lower() != first_contact.lower():
            add_to_caller_queue(caller_number, name)


async def add_towing_contacts(request: Request):
    """Populate the transfer queue with towing contacts."""
    caller_number = await get_caller_number(request)
    clear_caller_queue(caller_number)

    cm = ContactManager()
    for contact in cm.get_contacts_for_category("towing"):
        add_to_caller_queue(caller_number, contact.get("name", ""))


async def end_call(request: Request, with_message: bool = True):
    """Gracefully end the call, optionally thanking the caller."""
    caller_number = await get_caller_number(request)
    with new_response() as response:
        if with_message:
            message = (
                "Vielen Dank für deinen Anruf. Wir wünschen dir noch einen schönen Tag."
            )
            narrate(response, caller_number, message)
        save_job_info(caller_number, "hangup_reason", "Agent hat das Gespräch beendet")
        response.hangup()
        return send_request(request, response)


@router.api_route("/status", methods=["GET", "POST"])
async def status(request: Request):
    """Webhook that Twilio invokes to report the call status."""
    form = await request.form()
    caller_number = await get_caller_number(request)
    logger.info("Call status: %s", dict(form))

    if form.get("CallStatus") == "completed":
        save_job_info(caller_number, "Live", "Nein")

        if not get_job_info(caller_number, "hangup_reason"):
            save_job_info(caller_number, "hangup_reason", "Anruf durch Kunde beendet")

    return JSONResponse(content={"status": "ok"})


@router.api_route("/parse-transfer-call/{name}", methods=["GET", "POST"])
async def parse_transfer_call(request: Request, name: str):
    """Handle the status callback for each attempted transfer."""
    form_data = await request.form()
    caller_number = await get_caller_number(request)

    logger.info("Transfer call status: %s", form_data.get("DialCallStatus"))
    delete_next_caller(caller_number)

    if form_data.get("DialCallStatus") != "completed":
        with new_response() as response:
            twilio_message(
                caller_number,
                f"Weiterleitung an {name} fehlgeschlagen mit Status {form_data.get('DialCallStatus')}",
            )
            save_job_info(caller_number, "Erfolgreich weitergeleitet", "Nein")
            status = start_transfer(response, caller_number)

            if status == "no_more_agents":
                message = "Leider sind alle unsere Mitarbeiter im Gespräch. Bitte rufe später erneut an."
                narrate(response, caller_number, message)
                save_job_info(
                    caller_number,
                    "hangup_reason",
                    "Agent hat das Gespräch beendet",
                )
                response.hangup()

            return send_request(request, response)

    logger.info("Successfully transferred call to %s", name)
    save_job_info(caller_number, "Erfolgreich weitergeleitet", "Ja")
    twilio_message(caller_number, f"Erfolgreich weitergeleitet an {name}")

    contact_manager = ContactManager()
    transferred_phone = contact_manager.get_phone(name)
    send_job_details_sms(caller_number, transferred_phone)
    set_transferred_to(caller_number, name)
    logger.info("Job details SMS sent to %s", transferred_phone)

    with new_response() as response:
        response.hangup()
        save_job_info(caller_number, "hangup_reason", "Erfolgreich weitergeleitet")
        return send_request(request, response)
