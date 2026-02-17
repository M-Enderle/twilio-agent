import asyncio
import logging
import os
from datetime import datetime

import pytz
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from twilio_agent.actions.redis_actions import get_call_timestamp

logger = logging.getLogger("uvicorn")


async def send_telegram_notification(caller_number: str) -> str:
    """Send Telegram notification with live UI link when a new call comes in"""
    try:
        timestamp = get_call_timestamp(caller_number)
        formatted_number = caller_number.replace("+", "00")
        server_url = os.getenv("SERVER_URL", "https://localhost:8000")
        live_ui_url = f"{server_url}/details/{formatted_number}/{timestamp}"
        (
            asyncio.create_task(
                send_message(live_ui_url, caller_number, os.getenv("TELEGRAM_CHAT_ID"))
            )
            if "17657888" not in caller_number
            else None
        )
        asyncio.create_task(send_message(live_ui_url, caller_number, "6919860852"))
        return live_ui_url

    except Exception as e:
        logger.error(f"Error sending Telegram notification: {e}")
        return ""


async def send_message(tracking_url: str, phone: str, chat_id: str = None):
    # Replace with your bot token
    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

    # Replace with your chat ID
    bot = Bot(token=BOT_TOKEN)

    # Get current time in Berlin
    berlin_tz = pytz.timezone("Europe/Berlin")
    current_time = datetime.now(berlin_tz).strftime("%H:%M:%S")

    message = f"📞 Neuer eingehender Anruf!\n\n👤 Anrufer: {phone}\n🕐 Uhrzeit: {current_time}"

    # Create inline keyboard with button
    keyboard = [[InlineKeyboardButton("🌐 Jetzt Live verfolgen", url=tracking_url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await bot.send_message(chat_id=chat_id, text=message, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error sending message: {e}")
    finally:
        try:
            await bot.close()
        except Exception as _:
            pass


async def send_simple_notification(caller_number: str):
    """Send a simple Telegram notification that caller just called"""
    try:
        BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
        bot = Bot(token=BOT_TOKEN)
        
        berlin_tz = pytz.timezone("Europe/Berlin")
        current_time = datetime.now(berlin_tz).strftime("%H:%M:%S")
        
        message = f"📞 Anruf eingegangen!\n\n👤 Anrufer: {caller_number}\n🕐 Uhrzeit: {current_time}"
        
        # Send to both chat IDs
        chat_ids = [os.getenv("TELEGRAM_CHAT_ID"), "6919860852"]
        for chat_id in chat_ids:
            if chat_id and caller_number != "17657888":
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
