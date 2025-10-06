import datetime
import json
import logging
import os
import zoneinfo

import yaml
from redis import Redis

logger = logging.getLogger("uvicorn")

REDIS_URL = os.getenv("REDIS_URL", "redis://:${REDIS_PASSWORD}@redis:6379")
redis = Redis.from_url(REDIS_URL)
tz = zoneinfo.ZoneInfo("Europe/Berlin")

persistance_time = 60 * 60  # 1 hour


def _set_hist_info(call_number: str, key: str, value: str) -> str:
    if call_number == "anonymous":
        return
    redis_content = redis.get(
        f"verlauf:{call_number.replace('+', '00')}:{redis.get(f'anrufe:{call_number}:gestartet_um').decode('utf-8')}:info"
    )
    if redis_content:
        content = yaml.safe_load(redis_content.decode("utf-8"))
    else:
        content = []
    content.append({key: value})
    redis.set(
        f"verlauf:{call_number.replace('+', '00')}:{redis.get(f'anrufe:{call_number}:gestartet_um').decode('utf-8')}:info",
        yaml.dump(content, default_flow_style=False, allow_unicode=True),
    )


def init_new_call(call_number: str):
    starttime = datetime.datetime.now(tz).strftime("%Y%m%dT%H%M%S")
    redis.set(f"anrufe:{call_number}:gestartet_um", starttime, ex=persistance_time)
    _set_hist_info(call_number, "Startzeit", datetime.datetime.now(tz).isoformat())
    _set_hist_info(call_number, "Anrufnummer", call_number)
    save_job_info(call_number, "Live", "Ja")


def get_intent(call_number: str) -> str:
    try:
        if call_number == "anonymous":
            return None
        return redis.get(f"anrufe:{call_number}:anliegen").decode("utf-8")
    except Exception as e:
        return None


def set_intent(call_number: str, intent: str):
    if call_number == "anonymous":
        return
    redis.set(f"anrufe:{call_number}:anliegen", intent, ex=persistance_time)
    _set_hist_info(call_number, "Anliegen", intent)


def agent_message(call_number: str, message: str):
    _save_message(call_number, message, "assistant")
    logger.info("Agent message: %s", message)


def user_message(call_number: str, message: str):
    _save_message(call_number, message, "user")
    logger.info("User message: %s", message)


def ai_message(call_number: str, message: str):
    _save_message(call_number, message, "AI")
    logger.info("AI: %s", message)


def twilio_message(call_number: str, message: str):
    _save_message(call_number, message, "twilio")
    logger.info("Twilio: %s", message)


def _save_message(call_number: str, message: str, role: str):
    start_time = redis.get(f"anrufe:{call_number}:gestartet_um")
    if not start_time:
        return

    key = f"verlauf:{call_number.replace('+', '00')}:{start_time.decode('utf-8')}:nachrichten"
    existing_messages = redis.get(key)

    if existing_messages:
        messages = yaml.safe_load(existing_messages.decode("utf-8"))
    else:
        messages = []

    messages.append({"role": role, "content": message})

    redis.set(
        key,
        yaml.dump(messages, default_flow_style=False, allow_unicode=True),
    )


def save_location(call_number: str, location: dict):
    redis.set(
        f"anrufe:{call_number}:standort",
        json.dumps(location, indent=2, ensure_ascii=False),
        ex=persistance_time,
    )
    _set_hist_info(call_number, "Standort", location)


def get_location(call_number: str) -> dict:
    return json.loads(redis.get(f"anrufe:{call_number}:standort").decode("utf-8"))


def get_shared_location(call_number: str) -> dict:
    location_data = redis.get(f"anrufe:{call_number}:geteilter_standort")
    if location_data:
        return json.loads(location_data.decode("utf-8"))
    return None


def add_to_caller_queue(caller: str, name: str):
    queue = json.loads(redis.get(f"anrufe:{caller}:warteschlange") or b"[]")
    queue.append(name)
    redis.set(f"anrufe:{caller}:warteschlange", json.dumps(queue), ex=persistance_time)


def get_next_caller_in_queue(caller: str) -> str:
    queue_data = redis.get(f"anrufe:{caller}:warteschlange")
    queue = json.loads(queue_data.decode("utf-8")) if queue_data else []
    return queue[0] if queue else None


def delete_next_caller(caller: str):
    queue = json.loads(redis.get(f"anrufe:{caller}:warteschlange") or b"[]")
    if queue:
        queue.pop(0)
    redis.set(f"anrufe:{caller}:warteschlange", json.dumps(queue), ex=persistance_time)


def clear_caller_queue(caller: str):
    redis.delete(f"anrufe:{caller}:warteschlange")


def set_transferred_to(caller: str, transferred_to: str):
    redis.set(f"anrufe:{caller}:weitergeleitet_an", transferred_to, ex=persistance_time)
    _set_hist_info(caller, "Weitergeleitet an", transferred_to)


def get_transferred_to(caller: str) -> str | None:
    return redis.get(f"anrufe:{caller}:weitergeleitet_an")


def save_job_info(caller: str, detail_name: str, detail_value: str):
    _set_hist_info(caller, detail_name, detail_value)
    redis.set(f"anrufe:{caller}:{detail_name}", detail_value, ex=persistance_time)


def get_job_info(caller: str, detail_name: str) -> str | None:
    detail = redis.get(f"anrufe:{caller}:{detail_name}")
    if detail:
        return detail.decode("utf-8")
    return None


def get_call_timestamp(call_number: str) -> str | None:
    """Get the timestamp for when a call was started"""
    try:
        if call_number == "anonymous":
            return None
        timestamp = redis.get(f"anrufe:{call_number}:gestartet_um")
        if timestamp:
            return timestamp.decode("utf-8")
        return None
    except Exception as e:
        logger.error(f"Error getting call timestamp: {e}")
        return None
