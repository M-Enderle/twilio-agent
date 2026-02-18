import asyncio
from fastapi import Request
from num2words import num2words
from twilio_agent.settings import settings, HumanAgentRequested
from twilio_agent.actions.twilio_actions import immediate_human_transfer, new_response, send_request, say, start_transfer
from twilio_agent.actions.redis_actions import (
    agent_message, get_service, save_job_info, user_message, ai_message, get_location, get_job_info,
    add_to_caller_queue, clear_caller_queue
)
from twilio.twiml.voice_response import Gather
from twilio_agent.utils.ai import yes_no_question
from twilio_agent.utils.pricing import get_price
from twilio_agent.utils.utils import call_info, plz_fallback_path
from logging import getLogger

logger = getLogger("PricingFlow")


def populate_contact_queue(caller_number: str, service: str, provider_name: str):
    """Populate the caller queue with contacts from the provider location."""
    clear_caller_queue(caller_number)

    # Get locations for the service
    service_config = settings.service(service)
    locations = service_config.locations

    # Find matching location by provider name
    matching_location = None
    for location in locations:
        if location.name.lower() == provider_name.lower():
            matching_location = location
            break

    # If no matching location found, use emergency contact as fallback
    if not matching_location:
        logger.warning(f"No location found for provider '{provider_name}', using emergency contact")
        emergency = service_config.emergency_contact
        if emergency.name and emergency.phone:
            add_to_caller_queue(caller_number, emergency.name, emergency.phone)
            logger.info(f"Added emergency contact {emergency.name} to queue for {caller_number}")
        return

    # Add all contacts from the location, sorted by position
    sorted_contacts = sorted(matching_location.contacts, key=lambda c: c.position)
    for contact in sorted_contacts:
        if contact.name and contact.phone:
            add_to_caller_queue(caller_number, contact.name, contact.phone)
            logger.info(f"Added contact {contact.name} (position {contact.position}) to queue for {caller_number}")

    logger.info(f"Populated queue with {len(sorted_contacts)} contacts for {caller_number}")


async def start_pricing_handler(request: Request) -> str:
    """Calculate and present pricing."""
    caller_number, called_number, form_data = await call_info(request)
    service = get_service(caller_number)

    logger.info(f"Starting pricing for caller {caller_number}, service: {service}")

    # Get location from Redis
    location = get_location(caller_number)
    if not location:
        logger.error(f"No location found for caller {caller_number}")
        response = new_response()
        say(response, "Es ist ein Fehler aufgetreten. Bitte versuche es erneut.")
        agent_message(caller_number, "Error: No location found in Redis")
        response.redirect(f"{settings.env.SERVER_URL}{plz_fallback_path(service)}")
        return send_request(request, response)

    latitude = location.get("latitude")
    longitude = location.get("longitude")

    if not latitude or not longitude:
        logger.error(f"Invalid coordinates for caller {caller_number}: {location}")
        response = new_response()
        say(response, "Es ist ein Fehler aufgetreten. Bitte versuche es erneut.")
        agent_message(caller_number, "Error: Invalid coordinates")
        response.redirect(f"{settings.env.SERVER_URL}{plz_fallback_path(service)}")
        return send_request(request, response)

    # Get pricing for the service
    try:
        price_euro, minutes, provider_name, provider_phone = get_price(service, longitude, latitude)

        # Save pricing info to Redis
        save_job_info(caller_number, "Preis", f"{price_euro}€")
        save_job_info(caller_number, "Ankunftszeit", f"{minutes} Minuten")
        save_job_info(caller_number, "Dienstleister", provider_name)
        save_job_info(caller_number, "Dienstleister Telefon", provider_phone)

        # Populate contact queue for transfer
        populate_contact_queue(caller_number, service, provider_name)

        # Convert price to German words
        price_words = num2words(price_euro, lang="de")

        # Convert minutes to hours and minutes format
        hours = minutes // 60
        remaining_minutes = minutes % 60

        if hours > 0 and remaining_minutes > 0:
            # e.g., "4 Stunden und 21 Minuten"
            hours_words = num2words(hours, lang="de")
            minutes_words = num2words(remaining_minutes, lang="de")
            # Use singular "Stunde" for 1 hour
            hour_unit = "Stunde" if hours == 1 else "Stunden"
            minute_unit = "Minute" if remaining_minutes == 1 else "Minuten"
            # Replace "eins" with "eine" for feminine nouns
            if hours == 1:
                hours_words = "eine"
            if remaining_minutes == 1:
                minutes_words = "eine"
            duration_formatted = f"{hours_words} {hour_unit} und {minutes_words} {minute_unit}"
        elif hours > 0:
            # e.g., "2 Stunden" or "eine Stunde" (exactly 60/120 minutes)
            hours_words = num2words(hours, lang="de")
            hour_unit = "Stunde" if hours == 1 else "Stunden"
            if hours == 1:
                hours_words = "eine"
            duration_formatted = f"{hours_words} {hour_unit}"
        else:
            # e.g., "25 Minuten" or "eine Minute"
            minutes_words = num2words(remaining_minutes, lang="de")
            minute_unit = "Minute" if remaining_minutes == 1 else "Minuten"
            if remaining_minutes == 1:
                minutes_words = "eine"
            duration_formatted = f"{minutes_words} {minute_unit}"

        # Present offer
        offer_message = settings.service(service).announcements.price_offer.format(
            price_words=price_words,
            minutes_words=duration_formatted
        )

        response = new_response()
        agent_message(caller_number, offer_message)
        gather = Gather(
            input="speech",
            action="/parse-connection-request",
            timeout=5,
            language="de-DE",
            speechTimeout="auto",
            enhanced=True,
            model="experimental_conversations",
        )
        say(gather, offer_message)
        say(gather, settings.service(service).announcements.price_offer_prompt)
        response.append(gather)
        # Fallback: retry if no input received
        response.redirect(f"{settings.env.SERVER_URL}/start-pricing")
        return send_request(request, response)

    except Exception as exc:
        logger.error(f"Error calculating pricing for caller {caller_number}: {exc}")
        # Transfer to human when pricing fails
        return await immediate_human_transfer(request, caller_number, service)


async def parse_connection_request_handler(request: Request) -> str:
    """Handle connection confirmation."""
    caller_number, called_number, form_data = await call_info(request)
    service = get_service(caller_number)

    transcription = form_data.get("SpeechResult", "")
    user_message(caller_number, transcription)

    try:
        accepts_connection, reasoning, duration, model_source = await asyncio.wait_for(
            yes_no_question(transcription, "Verbindungsanfrage"),
            timeout=6.0,
        )
        ai_message(caller_number, f"Connection request: {reasoning}", duration, model_source)

        if accepts_connection:
            # Start transfer using contact queue
            save_job_info(caller_number, "Verbindung akzeptiert", "Ja")
            logger.info(f"Caller {caller_number} accepted connection, starting transfer via queue")

            response = new_response()
            say(response, settings.service(service).announcements.transfer_message)
            agent_message(caller_number, "Starting transfer to provider contacts")

            # Use the contact queue to attempt transfers in order
            transfer_result = start_transfer(response, caller_number)

            if transfer_result == "no_more_agents":
                # Queue is empty - no contacts available
                logger.error(f"No contacts in queue for {caller_number}")
                say(response, "Leider ist momentan niemand erreichbar. Bitte versuche es später erneut.")
                save_job_info(caller_number, "hangup_reason", "Keine Kontakte verfügbar")
                response.hangup()
            elif transfer_result == "no_service":
                # Could not determine service
                logger.error(f"Could not determine service for {caller_number}")
                return await immediate_human_transfer(request, caller_number, service)
            # else: transfer_result == "transferring" - start_transfer already added Dial to response

            return send_request(request, response)
        else:
            # User declined connection
            save_job_info(caller_number, "Verbindung akzeptiert", "Nein")
            logger.info(f"Caller {caller_number} declined connection")
            response = new_response()
            say(response, settings.service(service).announcements.connection_declined)
            agent_message(caller_number, "User declined connection offer")
            return send_request(request, response)

    except asyncio.TimeoutError:
        ai_message(caller_number, "<Connection request timed out>", 6.0)
        logger.warning(f"Connection request timeout for caller {caller_number}")
        response = new_response()
        say(response, settings.service(service).announcements.connection_timeout)
        response.redirect(f"{settings.env.SERVER_URL}/start-pricing")
        return send_request(request, response)

    except HumanAgentRequested:
        logger.info(f"Caller {caller_number} requested human agent during connection request.")
        ai_message(caller_number, "<User requested human agent>", 0.0)
        return await immediate_human_transfer(request, caller_number, service)
