import base64
import datetime
import json
import logging
import os
import zoneinfo

import dotenv
import yaml
from redis import Redis

dotenv.load_dotenv()

logger = logging.getLogger("uvicorn")

REDIS_URL = os.getenv("REDIS_URL", "redis://:${REDIS_PASSWORD}@redis:6379")
redis = Redis.from_url(REDIS_URL)
tz = zoneinfo.ZoneInfo("Europe/Berlin")

persistance_time = 60 * 60  # 1 hour

DEFAULT_RECORDING_TYPE = "initial"
RECORDING_TYPE_ORDER = (DEFAULT_RECORDING_TYPE, "followup")
VALID_RECORDING_TYPES = set(RECORDING_TYPE_ORDER)


def _normalize_recording_type(recording_type: str | None) -> str:
    if not recording_type:
        return DEFAULT_RECORDING_TYPE
    candidate = str(recording_type).strip().lower()
    if candidate in VALID_RECORDING_TYPES:
        return candidate
    logger.warning(
        "Unknown recording_type '%s'; falling back to '%s'",
        recording_type,
        DEFAULT_RECORDING_TYPE,
    )
    return DEFAULT_RECORDING_TYPE


def _recording_key(
    number_without_plus: str, timestamp: str, recording_type: str
) -> str:
    return f"notdienststation:verlauf:{number_without_plus}:{timestamp}:recording:{recording_type}"


def _set_hist_info(call_number: str, key: str, value: str) -> str:
    start_time = redis.get(f"notdienststation:anrufe:{call_number}:gestartet_um")
    if not start_time:
        logger.debug(
            "Skipping history update for %s because no start time is stored.",
            call_number,
        )
        return

    history_key = f"notdienststation:verlauf:{call_number.replace('+', '00')}:{start_time.decode('utf-8')}:info"

    redis_content = redis.get(history_key)
    if redis_content:
        content = yaml.safe_load(redis_content.decode("utf-8"))
    else:
        content = []
    content.append({key: value})
    redis.set(
        history_key,
        yaml.dump(content, default_flow_style=False, allow_unicode=True),
    )


def init_new_call(call_number: str):
    starttime = datetime.datetime.now(tz).strftime("%Y%m%dT%H%M%S")
    redis.set(
        f"notdienststation:anrufe:{call_number}:gestartet_um",
        starttime,
        ex=persistance_time,
    )
    _set_hist_info(call_number, "Startzeit", datetime.datetime.now(tz).isoformat())
    _set_hist_info(call_number, "Anrufnummer", call_number)
    save_job_info(call_number, "Live", "Ja")


def get_intent(call_number: str, return_anonymou: bool = False) -> str:
    try:
        if call_number == "anonymous" and not return_anonymou:
            return None
        return redis.get(f"notdienststation:anrufe:{call_number}:anliegen").decode(
            "utf-8"
        )
    except Exception as e:
        return None


def set_intent(call_number: str, intent: str):
    if call_number == "anonymous":
        return
    redis.set(
        f"notdienststation:anrufe:{call_number}:anliegen", intent, ex=persistance_time
    )
    _set_hist_info(call_number, "Anliegen", intent)


def agent_message(call_number: str, message: str):
    _save_message(call_number, message, "assistant")
    logger.info("Agent message: %s", message)


def user_message(call_number: str, message: str):
    _save_message(call_number, message, "user")
    logger.info("User message: %s", message)


def ai_message(call_number: str, message: str, duration: float = None):
    if duration is not None:
        message_with_timing = f"{message} (took {duration:.3f}s)"
    else:
        message_with_timing = message
    _save_message(call_number, message_with_timing, "AI")
    logger.info("AI: %s", message_with_timing)


def google_message(call_number: str, message: str, duration: float | None = None):
    if duration is not None:
        message_with_timing = f"{message} (took {duration:.3f}s)"
    else:
        message_with_timing = message
    _save_message(call_number, message_with_timing, "google")
    logger.info("Google: %s", message_with_timing)


def twilio_message(call_number: str, message: str):
    _save_message(call_number, message, "twilio")
    logger.info("Twilio: %s", message)


def _save_message(call_number: str, message: str, role: str):
    start_time = redis.get(f"notdienststation:anrufe:{call_number}:gestartet_um")
    if not start_time:
        return

    key = f"notdienststation:verlauf:{call_number.replace('+', '00')}:{start_time.decode('utf-8')}:nachrichten"
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
        f"notdienststation:anrufe:{call_number}:standort",
        json.dumps(location, indent=2, ensure_ascii=False),
        ex=persistance_time,
    )
    _set_hist_info(call_number, "Standort", location)


def get_location(call_number: str) -> dict:
    return json.loads(
        redis.get(f"notdienststation:anrufe:{call_number}:standort").decode("utf-8")
    )


def get_shared_location(call_number: str) -> dict:
    location_data = redis.get(
        f"notdienststation:anrufe:{call_number}:geteilter_standort"
    )
    if location_data:
        return json.loads(location_data.decode("utf-8"))
    return None


def add_to_caller_queue(caller: str, name: str):
    queue = json.loads(
        redis.get(f"notdienststation:anrufe:{caller}:warteschlange") or b"[]"
    )
    queue.append(name)
    redis.set(
        f"notdienststation:anrufe:{caller}:warteschlange",
        json.dumps(queue),
        ex=persistance_time,
    )


def get_next_caller_in_queue(caller: str) -> str:
    queue_data = redis.get(f"notdienststation:anrufe:{caller}:warteschlange")
    queue = json.loads(queue_data.decode("utf-8")) if queue_data else []
    return queue[0] if queue else None


def delete_next_caller(caller: str):
    queue = json.loads(
        redis.get(f"notdienststation:anrufe:{caller}:warteschlange") or b"[]"
    )
    if queue:
        queue.pop(0)
    redis.set(
        f"notdienststation:anrufe:{caller}:warteschlange",
        json.dumps(queue),
        ex=persistance_time,
    )


def clear_caller_queue(caller: str):
    redis.delete(f"notdienststation:anrufe:{caller}:warteschlange")


def set_transferred_to(caller: str, transferred_to: str):
    redis.set(
        f"notdienststation:anrufe:{caller}:Weitergeleitet an",
        transferred_to,
        ex=persistance_time,
    )
    _set_hist_info(caller, "Weitergeleitet an", transferred_to)


def get_transferred_to(caller: str) -> str | None:
    return redis.get(f"notdienststation:anrufe:{caller}:Weitergeleitet an")


def save_job_info(caller: str, detail_name: str, detail_value: str):
    _set_hist_info(caller, detail_name, detail_value)
    redis.set(
        f"notdienststation:anrufe:{caller}:{detail_name}",
        detail_value,
        ex=persistance_time,
    )


def delete_job_info(caller: str, detail_name: str):
    redis.delete(f"notdienststation:anrufe:{caller}:{detail_name}")


def get_job_info(caller: str, detail_name: str) -> str | None:
    detail = redis.get(f"notdienststation:anrufe:{caller}:{detail_name}")
    if detail:
        return detail.decode("utf-8")
    return None


def get_call_timestamp(call_number: str) -> str | None:
    """Get the timestamp for when a call was started"""
    try:
        timestamp = redis.get(f"notdienststation:anrufe:{call_number}:gestartet_um")
        if timestamp:
            return timestamp.decode("utf-8")
        return None
    except Exception as e:
        logger.error(f"Error getting call timestamp: {e}")
        return None


def save_call_recording(
    call_number: str,
    recording_bytes: bytes,
    content_type: str = "audio/mpeg",
    metadata: dict | None = None,
    recording_type: str | None = None,
):
    if not call_number or not recording_bytes or call_number == "anonymous":
        return

    start_time = redis.get(f"notdienststation:anrufe:{call_number}:gestartet_um")
    if not start_time:
        return

    key_suffix = start_time.decode("utf-8")
    normalized_type = _normalize_recording_type(recording_type)
    number_without_plus = call_number.replace("+", "00")
    redis_key = _recording_key(number_without_plus, key_suffix, normalized_type)

    logger.info(
        "Saving %s recording for %s with key %s (bytes=%d)",
        normalized_type,
        call_number,
        redis_key,
        len(recording_bytes),
    )
    payload_obj = {
        "content_type": content_type,
        "data": base64.b64encode(recording_bytes).decode("ascii"),
        "recording_type": normalized_type,
    }
    if metadata:
        payload_obj["metadata"] = metadata

    if metadata and "duration_total_seconds" in metadata:
        logger.info(
            "Saving recording for %s (total_duration=%ss, bytes=%d)",
            call_number,
            metadata.get("duration_total_seconds"),
            len(recording_bytes),
        )

    recording_payload = json.dumps(payload_obj)

    redis.set(redis_key, recording_payload)

    if normalized_type == DEFAULT_RECORDING_TYPE:
        save_job_info(call_number, "Audioaufnahme", "Verfügbar")
        save_job_info(call_number, "Audioaufnahme (Erstanruf)", "Verfügbar")
    else:
        save_job_info(call_number, "Audioaufnahme (SMS Rückruf)", "Verfügbar")


def get_call_recording(number: str, timestamp: str, recording_type: str | None = None):
    if not number or not timestamp:
        return None

    normalized_type = _normalize_recording_type(recording_type)
    number = number.replace("+", "00")

    redis_key = _recording_key(number, timestamp, normalized_type)
    recording_data = redis.get(redis_key)

    if not recording_data:
        return None

    try:
        payload = json.loads(recording_data.decode("utf-8"))
        payload.setdefault("recording_type", normalized_type)
        return payload
    except Exception as exc:
        logger.error(
            "Failed to load recording for %s at %s: %s", number, timestamp, exc
        )
        return None


def get_call_recording_binary(
    number: str, timestamp: str, recording_type: str | None = None
):
    """Return decoded audio bytes and content type for a stored recording."""
    payload = get_call_recording(number, timestamp, recording_type)
    if not payload:
        return None, None

    data_field = payload.get("data")
    if not data_field:
        return None, None

    try:
        audio_bytes = base64.b64decode(data_field)
    except Exception as exc:
        logger.error(
            "Failed to decode recording for %s at %s: %s", number, timestamp, exc
        )
        return None, None

    return audio_bytes, payload.get("content_type", "audio/mpeg")


def get_available_recordings(number: str, timestamp: str) -> dict[str, dict]:
    recordings: dict[str, dict] = {}
    for recording_type in RECORDING_TYPE_ORDER:
        payload = get_call_recording(number, timestamp, recording_type)
        if payload:
            recordings[recording_type] = payload
    return recordings


def cleanup_call(call_number: str):
    start_time = redis.get(f"notdienststation:anrufe:{call_number}:gestartet_um")
    if not start_time:
        return

    keys_to_delete = [
        f"notdienststation:anrufe:{call_number}:gestartet_um",
        f"notdienststation:anrufe:{call_number}:warteschlange",
    ]

    logger.warning(f"Cleaning up call data for {call_number}: {keys_to_delete}")

    for key in keys_to_delete:
        redis.delete(key)
