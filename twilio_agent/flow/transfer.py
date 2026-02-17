import logging
from urllib.parse import unquote
from fastapi import Request
from twilio_agent.actions.twilio_actions import new_response, send_request, say, send_job_details_sms, start_transfer
from twilio_agent.actions.redis_actions import (
    delete_next_caller, save_job_info, set_transferred_to, agent_message, get_service
)
from twilio_agent.settings import settings
from twilio_agent.utils.utils import call_info

logger = logging.getLogger("TransferFlow")


async def parse_transfer_call_handler(request: Request, name: str, phone: str) -> str:
    """Handle the result of a transfer attempt to a contact in the queue."""
    caller_number, called_number, form_data = await call_info(request)
    service = get_service(caller_number)

    # URL-decode the name and phone from the path parameters
    contact_name = unquote(name)
    contact_phone = unquote(phone)

    # Get the dial status from Twilio
    dial_status = form_data.get("DialCallStatus", "")

    logger.info(
        f"Transfer attempt for {caller_number} to {contact_name} ({contact_phone}): "
        f"Status={dial_status}"
    )

    with new_response() as response:
        # Check if the transfer was successful
        if dial_status in ["completed", "answered"]:
            # Transfer succeeded
            logger.info(f"Transfer successful: {caller_number} → {contact_name}")

            save_job_info(caller_number, "Erfolgreich weitergeleitet", "Ja")
            save_job_info(caller_number, "Weitergeleitet an", contact_name)
            agent_message(caller_number, f"Successfully transferred to {contact_name} ({contact_phone})")

            # Send job details SMS to the agent who answered
            try:
                send_job_details_sms(caller_number, contact_phone)
            except Exception as exc:
                logger.error(f"Failed to send job details SMS to {contact_phone}: {exc}")

            # Remember this contact for repeat calls
            set_transferred_to(caller_number, contact_phone)

            # Keep contact in queue during active transfer (shows who is currently connected)
            # Queue will be cleaned up when call ends via status callback

            # End the call - the transfer is complete
            response.hangup()

        else:
            # Transfer failed (no-answer, busy, failed, etc.)
            logger.warning(
                f"Transfer failed: {caller_number} → {contact_name} "
                f"(Status: {dial_status}). Trying next contact in queue."
            )

            save_job_info(caller_number, "Erfolgreich weitergeleitet", "Nein")
            agent_message(
                caller_number,
                f"Transfer to {contact_name} failed ({dial_status}). Trying next contact..."
            )

            # Remove failed contact from queue and try the next one
            delete_next_caller(caller_number)

            # Try the next contact in the queue
            transfer_result = start_transfer(response, caller_number)

            if transfer_result == "no_more_agents":
                # No more contacts in queue - inform caller and hang up
                logger.error(f"No more contacts available for {caller_number}")
                say(
                    response,
                    "Leider ist momentan niemand erreichbar. Bitte versuche es später erneut."
                )
                agent_message(caller_number, "All transfer attempts failed - no more contacts in queue")
                save_job_info(caller_number, "hangup_reason", "Keine Mitarbeiter erreichbar")
                response.hangup()
            elif transfer_result == "no_service":
                # Could not determine service
                logger.error(f"Could not determine service for {caller_number} during transfer retry")
                say(response, "Ein technischer Fehler ist aufgetreten.")
                save_job_info(caller_number, "hangup_reason", "Technischer Fehler bei Weiterleitung")
                response.hangup()
            # else: transfer_result == "transferring" - start_transfer already added Dial to response

        return send_request(request, response)
