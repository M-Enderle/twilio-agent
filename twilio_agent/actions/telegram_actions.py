import asyncio
import logging
from datetime import datetime

import pytz
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from twilio_agent.actions.redis_actions import get_call_timestamp
from twilio_agent.settings import settings

logger = logging.getLogger("TelegramActions")


async def send_telegram_notification(caller_number: str, service_id: str = None) -> str:
    """Send Telegram notification with live UI link when a new call comes in

    Args:
        caller_number: The phone number of the caller
        service_id: The service ID (schluessel-allgaeu, notdienst-schluessel, notdienst-abschlepp)
    """
    try:
        timestamp = get_call_timestamp(caller_number)
        dashboard_url = settings.env.DASHBOARD_URL or settings.env.SERVER_URL
        live_ui_url = f"{dashboard_url}/anrufe?nummer={caller_number}&ts={timestamp}"

        # Only send Telegram messages if the URL is not localhost (Telegram doesn't accept localhost URLs)
        is_localhost = "localhost" in live_ui_url or "127.0.0.1" in live_ui_url

        if is_localhost:
            logger.warning(f"Skipping Telegram notification - localhost URL not supported: {live_ui_url}")
        else:
            # Get service-specific bot token from env
            bot_token = settings.get_telegram_bot_token(service_id) if service_id else None

            # All chat IDs from env
            chat_ids = settings.get_telegram_chat_ids()

            if bot_token and chat_ids:
                for chat_id in chat_ids:
                    asyncio.create_task(
                        send_message(live_ui_url, caller_number, chat_id, bot_token, service_id)
                    )
            else:
                logger.warning(f"No Telegram bot configured for service {service_id}")

        return live_ui_url

    except Exception as e:
        logger.error(f"Error sending Telegram notification: {e}")
        return ""


async def send_message(tracking_url: str, phone: str, chat_id: str = None, bot_token: str = None, service_id: str = None):
    """Send a Telegram message with live tracking link

    Args:
        tracking_url: URL to the live tracking page
        phone: Caller phone number
        chat_id: Telegram chat ID to send to
        bot_token: Telegram bot token (if not provided, uses env variable)
        service_id: Service ID to include in message (optional)
    """
    if not bot_token:
        bot_token = settings.env.TELEGRAM_BOT_TOKEN.get_secret_value() if settings.env.TELEGRAM_BOT_TOKEN else None

    if not bot_token:
        logger.error("TELEGRAM_BOT_TOKEN not configured")
        return

    bot = Bot(token=bot_token)

    # Get current time in Berlin
    berlin_tz = pytz.timezone("Europe/Berlin")
    current_time = datetime.now(berlin_tz).strftime("%H:%M:%S")

    # Include service name in message
    service_emoji = {
        "schluessel-allgaeu": "🔑",
        "notdienst-schluessel": "🔑",
        "notdienst-abschlepp": "🚗"
    }
    service_prefix = f"{service_emoji.get(service_id, '📞')} " if service_id else ""

    message = f"{service_prefix}Neuer eingehender Anruf!\n\n👤 Anrufer: {phone}\n🕐 Uhrzeit: {current_time}"

    # Create inline keyboard with button
    keyboard = [[InlineKeyboardButton("🌐 Jetzt Live verfolgen", url=tracking_url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await bot.send_message(chat_id=chat_id, text=message, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error sending message to {chat_id}: {e}")
    finally:
        try:
            await bot.close()
        except Exception as _:
            pass


async def send_simple_notification(caller_number: str, service_id: str = None):
    """Send a simple Telegram notification that caller just called

    Args:
        caller_number: The phone number of the caller
        service_id: The service ID (schluessel-allgaeu, notdienst-schluessel, notdienst-abschlepp)
    """
    try:
        # Get service-specific bot token from env
        bot_token = settings.get_telegram_bot_token(service_id) if service_id else None

        # All chat IDs from env
        chat_ids = settings.get_telegram_chat_ids()

        if not bot_token:
            logger.error("TELEGRAM_BOT_TOKEN not configured")
            return

        bot = Bot(token=bot_token)

        berlin_tz = pytz.timezone("Europe/Berlin")
        current_time = datetime.now(berlin_tz).strftime("%H:%M:%S")

        # Include service name in message
        service_emoji = {
            "schluessel-allgaeu": "🔑",
            "notdienst-schluessel": "🔑",
            "notdienst-abschlepp": "🚗"
        }
        service_prefix = f"{service_emoji.get(service_id, '📞')} " if service_id else ""

        message = f"{service_prefix}Anruf eingegangen!\n\n👤 Anrufer: {caller_number}\n🕐 Uhrzeit: {current_time}"
        if service_id:
            message += f"\n🏢 Service: {service_id}"

        # Send to all configured chat IDs
        if caller_number != "17657888":
            for chat_id in chat_ids:
                try:
                    await bot.send_message(chat_id=chat_id, text=message)
                except Exception as e:
                    logger.error(f"Error sending message to {chat_id}: {e}")

        await bot.close()
    except Exception as e:
        logger.error(f"Error sending simple notification: {e}")


if __name__ == "__main__":
    # Example usage with a URL parameter
    url = "https://example.com/track/call123"
    asyncio.run(send_message(url, "+491234567890"))
