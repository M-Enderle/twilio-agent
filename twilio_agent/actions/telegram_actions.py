import asyncio
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
import dotenv
import os
from datetime import datetime
import pytz

dotenv.load_dotenv()

async def send_message(tracking_url: str, phone: str):
    # Replace with your bot token
    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    
    # Replace with your chat ID
    CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
    
    bot = Bot(token=BOT_TOKEN)
    
    # Get current time in Berlin
    berlin_tz = pytz.timezone('Europe/Berlin')
    current_time = datetime.now(berlin_tz).strftime('%H:%M:%S')
    
    message = f"📞 Neuer eingehender Anruf!\n\n👤 Anrufer: {phone}\n🕐 Uhrzeit: {current_time}"
    
    # Create inline keyboard with button
    keyboard = [[InlineKeyboardButton("🌐 Jetzt Live verfolgen", url=tracking_url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await bot.send_message(chat_id=CHAT_ID, text=message, reply_markup=reply_markup)
        print("Message sent successfully!")
    except Exception as e:
        print(f"Error sending message: {e}")
    finally:
        try:
            await bot.close()
        except Exception as _:
            pass

if __name__ == "__main__":
    # Example usage with a URL parameter
    url = "https://example.com/track/call123"
    asyncio.run(send_message(url, "+491234567890"))