import datetime
import json
import logging
import time

import starlette.datastructures
from redis import Redis

logger = logging.getLogger("uvicorn")

redis = Redis(host="localhost", port=6379)


def get_intent(call_number: str) -> str:
    try:
        if call_number == "anonymous":  # TODO: Check this
            return None
        return redis.get(f"callers:{call_number}:intent").decode("utf-8")
    except Exception as e:
        return None


def set_intent(call_number: str, intent: str):
    if call_number == "anonymous":  # TODO: Check this
        return
    redis.set(f"callers:{call_number}:intent", intent, ex=60 * 60 * 24)  # 1 day


def save_caller_info(call_number: str, form: starlette.datastructures.FormData):
    form_data = {k: form.getlist(k) for k in form}

    # check if there is already a caller info
    existing_caller_info = redis.get(f"callers:{call_number}:info")
    if existing_caller_info:
        timestamp = json.loads(existing_caller_info.decode("utf-8"))["timestamp"]
        conversation = redis.get(f"callers:{call_number}:messages")

        # Only save conversation if it exists and is not None
        if conversation is not None:
            redis.set(
                f"callers:{call_number}:history:{timestamp.replace(':', '.')}:messages",
                conversation,
                ex=60 * 60 * 24 * 365,
            )  # 365 days

        redis.set(
            f"callers:{call_number}:history:{timestamp.replace(':', '.')}:info",
            existing_caller_info,
            ex=60 * 60 * 24 * 365,
        )  # 365 days
        redis.delete(f"callers:{call_number}:messages")
        redis.delete(f"callers:{call_number}:info")
        redis.delete(f"callers:{call_number}:location")
        redis.delete(f"callers:{call_number}:contact")

    # add timestamp
    german_tz = datetime.timezone(datetime.timedelta(hours=1))  # CET
    form_data["timestamp"] = datetime.datetime.now(german_tz).strftime(
        "%d.%m.%Y %H:%M:%S"
    )

    redis.set(
        f"callers:{call_number}:info",
        json.dumps(form_data, indent=2),
        ex=60 * 60 * 24 * 30,
    )  # 30 days


def agent_message(call_number: str, message: str):
    _save_message(call_number, message, "assistant")
    logger.info("Agent message: %s", message)


def user_message(call_number: str, message: str):
    _save_message(call_number, message, "user")
    logger.info("User message: %s", message)


def ai_message(call_number: str, message: str):
    _save_message(call_number, message, "grok")
    logger.info("Grok: %s", message)


def _save_message(call_number: str, message: str, role: str):
    existing_messages = redis.get(f"callers:{call_number}:messages")
    if existing_messages:
        messages = json.loads(existing_messages.decode("utf-8"))
    else:
        messages = []

    # Add new message to list
    messages.append({"role": role, "content": message})

    # Save updated messages list
    redis.set(
        f"callers:{call_number}:messages",
        json.dumps(messages, indent=2, ensure_ascii=False),
        ex=60 * 60 * 24,
    )  # 1 day


def save_location(call_number: str, location: dict):
    redis.set(
        f"callers:{call_number}:location",
        json.dumps(location, indent=2, ensure_ascii=False),
        ex=60 * 60 * 24,
    )  # 1 day


def get_location(call_number: str) -> dict:
    return json.loads(redis.get(f"callers:{call_number}:location").decode("utf-8"))


def save_caller_contact(call_number: str, name: str, phone: str):
    redis.set(
        f"callers:{call_number}:contact",
        json.dumps({"name": name, "phone": phone}, indent=2, ensure_ascii=False),
        ex=60 * 60 * 24,
    )  # 1 day


def get_caller_contact(call_number: str) -> dict | None:
    contact_data = redis.get(f"callers:{call_number}:contact")
    if contact_data:
        return json.loads(contact_data.decode("utf-8"))
    return None


def get_shared_location(call_number: str) -> dict:
    location_data = redis.get(f"callers:{call_number}:shared_location")
    if location_data:
        return json.loads(location_data.decode("utf-8"))
    return None


if __name__ == "__main__":
    print(get_intent("+4917657888987"))
    set_intent("+4917657888987", "Schlüsseldienst")
    print(get_intent("+4917657888987"))
