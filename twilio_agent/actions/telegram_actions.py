"""Telegram notification actions for incoming call alerts.

Sends notifications to configured Telegram chats when new calls arrive,
including live tracking links and caller information.
"""

import asyncio
import logging
import zoneinfo
from datetime import datetime
from typing import Optional

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from twilio_agent.actions.redis_actions import get_call_timestamp
from twilio_agent.settings import settings

logger = logging.getLogger("TelegramActions")

_BERLIN_TZ = zoneinfo.ZoneInfo("Europe/Berlin")

_SERVICE_EMOJI = {
    "schluessel-allgaeu": "\U0001f511",
    "notdienst-schluessel": "\U0001f511",
    "notdienst-abschlepp": "\U0001f697",
}


def _get_berlin_time() -> str:
    """Return the current time in Europe/Berlin formatted as HH:MM:SS."""
    return datetime.now(_BERLIN_TZ).strftime("%H:%M:%S")


def _is_localhost_url(url: str) -> bool:
    """Check whether a URL points to localhost."""
    return "localhost" in url or "127.0.0.1" in url


async def send_telegram_notification(
    caller_number: str, service_id: Optional[str] = None
) -> str:
    """Send Telegram notification with live UI link when a new call comes in.

    Args:
        caller_number: The phone number of the caller.
        service_id: The service ID (e.g. schluessel-allgaeu,
            notdienst-schluessel, notdienst-abschlepp).

    Returns:
        The live UI URL for the call, or an empty string on failure.
    """
    try:
        timestamp = get_call_timestamp(caller_number)
        dashboard_url = (
            settings.env.DASHBOARD_URL or settings.env.SERVER_URL
        ).replace("http://", "https://")
        normalized_number = caller_number.replace("+", "00")
        live_ui_url = (
            f"{dashboard_url}/anrufe"
            f"?nummer={normalized_number}&ts={timestamp}"
        )

        if _is_localhost_url(live_ui_url):
            logger.warning(
                "Skipping Telegram notification - localhost URL "
                "not supported: %s",
                live_ui_url,
            )
        else:
            bot_token = (
                settings.get_telegram_bot_token(service_id)
                if service_id
                else None
            )
            chat_ids = settings.get_telegram_chat_ids()

            if bot_token and chat_ids:
                for chat_id in chat_ids:
                    asyncio.create_task(
                        send_message(
                            live_ui_url,
                            caller_number,
                            chat_id,
                            bot_token,
                        )
                    )
            else:
                logger.warning(
                    "No Telegram bot configured for service %s",
                    service_id,
                )

        return live_ui_url

    except Exception as e:
        logger.error("Error sending Telegram notification: %s", e)
        return ""


async def send_message(
    tracking_url: str,
    phone: str,
    chat_id: Optional[str] = None,
    bot_token: Optional[str] = None,
) -> None:
    """Send a Telegram message with a live tracking link.

    Args:
        tracking_url: URL to the live tracking page.
        phone: Caller phone number.
        chat_id: Telegram chat ID to send to.
        bot_token: Telegram bot token. Falls back to the legacy
            environment variable when not provided.
    """
    if not bot_token:
        bot_token = (
            settings.env.TELEGRAM_BOT_TOKEN.get_secret_value()
            if settings.env.TELEGRAM_BOT_TOKEN
            else None
        )

    if not bot_token:
        logger.error("TELEGRAM_BOT_TOKEN not configured")
        return

    bot = Bot(token=bot_token)

    current_time = _get_berlin_time()
    message = (
        f"Neuer eingehender Anruf!\n\n"
        f"\U0001f464 Anrufer: {phone}\n"
        f"\U0001f550 Uhrzeit: {current_time}"
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "\U0001f310 Jetzt Live verfolgen", url=tracking_url
            )
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await bot.send_message(
            chat_id=chat_id, text=message, reply_markup=reply_markup
        )
    except Exception as e:
        logger.error("Error sending message to %s: %s", chat_id, e)
    finally:
        try:
            await bot.close()
        except Exception:
            pass


async def send_simple_notification(
    caller_number: str, service_id: Optional[str] = None
) -> None:
    """Send a simple Telegram notification that a caller just called.

    Args:
        caller_number: The phone number of the caller.
        service_id: The service ID (e.g. schluessel-allgaeu,
            notdienst-schluessel, notdienst-abschlepp).
    """
    bot = None
    try:
        bot_token = (
            settings.get_telegram_bot_token(service_id)
            if service_id
            else None
        )
        chat_ids = settings.get_telegram_chat_ids()

        if not bot_token:
            logger.error("TELEGRAM_BOT_TOKEN not configured")
            return

        bot = Bot(token=bot_token)

        current_time = _get_berlin_time()

        default_emoji = "\U0001f4de"
        emoji = _SERVICE_EMOJI.get(service_id, default_emoji)
        service_prefix = f"{emoji} " if service_id else ""

        message = (
            f"{service_prefix}Anruf eingegangen!\n\n"
            f"\U0001f464 Anrufer: {caller_number}\n"
            f"\U0001f550 Uhrzeit: {current_time}"
        )
        if service_id:
            message += f"\n\U0001f3e2 Service: {service_id}"

        # NOTE: caller_number "17657888" is filtered out intentionally
        # (test/internal number). Consider moving to configuration.
        if caller_number != "17657888":
            for chat_id in chat_ids:
                try:
                    await bot.send_message(
                        chat_id=chat_id, text=message
                    )
                except Exception as e:
                    logger.error(
                        "Error sending message to %s: %s", chat_id, e
                    )
    except Exception as e:
        logger.error("Error sending simple notification: %s", e)
    finally:
        if bot is not None:
            try:
                await bot.close()
            except Exception:
                pass


if __name__ == "__main__":
    url = "https://example.com/track/call123"
    asyncio.run(send_message(url, "+491234567890"))
