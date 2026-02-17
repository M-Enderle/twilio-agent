"""Contact queue management and transfer related endpoints."""

from __future__ import annotations

import json
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
from twilio_agent.utils.settings import SettingsManager

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_phone_for_contact(name: str, phone: str) -> str:
    """Return substitute phone if vacation mode is active and contact is Andi."""
    sm = SettingsManager()
    vacation = sm.get_vacation_mode()
    if vacation.get("active") and name.lower() == "andi":
        logger.warning("Vacation mode active, substituting Andi's phone number with %s", vacation.get("substitute_phone", ""))
        substitute = vacation.get("substitute_phone", "")
        if substitute:
            return substitute
    return phone


async def add_locksmith_contacts(request: Request):
    """Populate the transfer queue with locksmith contacts from Redis order."""
    caller_number = await get_caller_number(request)
    clear_caller_queue(caller_number)

    cm = ContactManager()
    sm = SettingsManager()
    first_contact_name = get_job_info(caller_number, "Anbieter") or sm.get_emergency_contact()
    contacts = cm.get_contacts_for_category("locksmith")

    # If a specific provider was determined (e.g. by pricing), add them first
    for contact in contacts:
        if contact.get("name", "").lower() == first_contact_name.lower():
            name = contact.get("name", "")
            phone = _get_phone_for_contact(name, contact.get("phone", ""))
            add_to_caller_queue(caller_number, name, phone)

            # Add all fallbacks from this contact
            fallbacks_json = contact.get("fallbacks_json", "")
            if fallbacks_json:
                fallbacks = json.loads(fallbacks_json)
                for fb in fallbacks:
                    fb_name = fb.get("name", "")
                    fb_phone = _get_phone_for_contact(fb_name, fb.get("phone", ""))
                    add_to_caller_queue(caller_number, fb_name, fb_phone)
            break


async def add_towing_contacts(request: Request):
    """Populate the transfer queue with towing contacts from Redis order."""
    caller_number = await get_caller_number(request)
    clear_caller_queue(caller_number)

    cm = ContactManager()
    sm = SettingsManager()
    first_contact_name = get_job_info(caller_number, "Anbieter") or sm.get_emergency_contact()
    contacts = cm.get_contacts_for_category("towing")

    # If a specific provider was determined (e.g. by pricing), add them first
    for contact in contacts:
        if contact.get("name", "").lower() == first_contact_name.lower():
            name = contact.get("name", "")
            phone = _get_phone_for_contact(name, contact.get("phone", ""))
            add_to_caller_queue(caller_number, name, phone)

            # Add all fallbacks from this contact
            fallbacks_json = contact.get("fallbacks_json", "")
            if fallbacks_json:
                fallbacks = json.loads(fallbacks_json)
                for fb in fallbacks:
                    fb_name = fb.get("name", "")
                    fb_phone = _get_phone_for_contact(fb_name, fb.get("phone", ""))
                    add_to_caller_queue(caller_number, fb_name, fb_phone)
            break


async def add_default_contacts(request: Request):
    """Populate the transfer queue with the emergency contact from settings."""
    caller_number = await get_caller_number(request)
    clear_caller_queue(caller_number)

    sm = SettingsManager()
    emergency = sm.get_emergency_contact()
    contact_id = emergency.get("contact_id")

    logging.info("Adding default contacts to queue, emergency contact ID: %s", contact_id)

    if contact_id:
        cm = ContactManager()
        # Find the contact by ID across all categories to get the phone number
        for category in ("locksmith", "towing"):
            for contact in cm.get_contacts_for_category(category):
                if contact.get("id") == contact_id:
                    # Add the emergency contact first
                    name = contact.get("name", "")
                    phone = _get_phone_for_contact(name, contact.get("phone", ""))
                    add_to_caller_queue(caller_number, name, phone)

                    # Add all fallbacks from this contact
                    fallbacks_json = contact.get("fallbacks_json", "")
                    if fallbacks_json:
                        fallbacks = json.loads(fallbacks_json)
                        for fb in fallbacks:
                            fb_name = fb.get("name", "")
                            fb_phone = _get_phone_for_contact(fb_name, fb.get("phone", ""))
                            add_to_caller_queue(caller_number, fb_name, fb_phone)
                    return


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


@router.api_route("/parse-transfer-call/{name}/{phone}", methods=["GET", "POST"])
async def parse_transfer_call(request: Request, name: str, phone: str):
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

    send_job_details_sms(caller_number, phone)
    set_transferred_to(caller_number, name)
    logger.info("Job details SMS sent to %s", phone)

    with new_response() as response:
        response.hangup()
        save_job_info(caller_number, "hangup_reason", "Erfolgreich weitergeleitet")
        return send_request(request, response)
