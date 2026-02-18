"""Redis-backed data layer for active call state and call history.

Provides helpers for storing and retrieving per-call metadata, conversation
messages, location data, caller queues, recordings, and transcriptions.
All active-call keys expire after ``PERSISTENCE_TIME`` seconds.
"""

import base64
import datetime
import json
import logging
import os
import zoneinfo
from typing import Any

import yaml  # kept for backwards-compatible reads of legacy YAML data
from redis import Redis

logger = logging.getLogger("uvicorn")

REDIS_URL = os.getenv("REDIS_URL", "redis://:${REDIS_PASSWORD}@redis:6379")
redis = Redis.from_url(REDIS_URL)
_TZ = zoneinfo.ZoneInfo("Europe/Berlin")

PERSISTENCE_TIME = 60 * 60  # 1 hour

_KEY_PREFIX = "notdienststation"

DEFAULT_RECORDING_TYPE = "initial"
RECORDING_TYPE_ORDER = (DEFAULT_RECORDING_TYPE, "followup")
VALID_RECORDING_TYPES = set(RECORDING_TYPE_ORDER)


def _loads_json_or_yaml(raw: bytes) -> Any:
    """Deserialize bytes as JSON, falling back to YAML for legacy data."""
    text = raw.decode("utf-8")
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return yaml.safe_load(text)


def _normalize_phone(number: str) -> str:
    """Replace '+' with '00' for use in Redis keys."""
    return number.replace("+", "00")


def _active_call_key(call_number: str, suffix: str) -> str:
    """Build a Redis key for active-call data."""
    return f"{_KEY_PREFIX}:anrufe:{call_number}:{suffix}"


def _history_key(number_without_plus: str, timestamp: str, suffix: str) -> str:
    """Build a Redis key for call-history data."""
    return f"{_KEY_PREFIX}:verlauf:{number_without_plus}:{timestamp}:{suffix}"


def _normalize_recording_type(recording_type: str | None) -> str:
    """Return a valid recording type, falling back to the default."""
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
    """Build a Redis key for a call recording."""
    return _history_key(
        number_without_plus, timestamp, f"recording:{recording_type}"
    )


def _format_timed_message(message: str, duration: float | None) -> str:
    """Append elapsed time to *message* when *duration* is provided."""
    if duration is not None:
        return f"{message} (took {duration:.3f}s)"
    return message


def _get_start_time(call_number: str) -> str | None:
    """Return the decoded start-time string for *call_number*, or ``None``."""
    raw = redis.get(_active_call_key(call_number, "gestartet_um"))
    return raw.decode("utf-8") if raw else None


def _set_hist_info(call_number: str, key: str, value: Any) -> None:
    """Upsert a key/value pair into the call-history info list."""
    start_time = _get_start_time(call_number)
    if not start_time:
        logger.debug(
            "Skipping history update for %s because no start time is stored.",
            call_number,
        )
        return

    hist_key = _history_key(
        _normalize_phone(call_number), start_time, "info"
    )

    redis_content = redis.get(hist_key)
    if redis_content:
        content = _loads_json_or_yaml(redis_content)
        if not isinstance(content, list):
            logger.warning(
                "History info for %s was not a list; resetting.", call_number
            )
            content = []
    else:
        content = []

    # Remove any existing entries with the same key to avoid duplicates
    filtered = [
        entry for entry in content if not (isinstance(entry, dict) and key in entry)
    ]
    filtered.append({key: value})

    redis.set(
        hist_key,
        json.dumps(filtered, ensure_ascii=False),
    )


def init_new_call(call_number: str, service: str) -> None:
    """Initialise Redis state for a new incoming call."""
    starttime = datetime.datetime.now(_TZ).strftime("%Y%m%dT%H%M%S")
    redis.set(
        _active_call_key(call_number, "gestartet_um"),
        starttime,
        ex=PERSISTENCE_TIME,
    )
    _set_hist_info(call_number, "Startzeit", datetime.datetime.now(_TZ).isoformat())
    _set_hist_info(call_number, "Anrufnummer", call_number)
    _set_hist_info(call_number, "Service", service)
    save_job_info(call_number, "Live", "Ja")
    save_job_info(call_number, "Service", service)


def get_service(call_number: str) -> str | None:
    """Return the service identifier associated with the active call."""
    return get_job_info(call_number, "Service")


def agent_message(call_number: str, message: str) -> None:
    """Log a message from the voice agent."""
    _save_message(call_number, message, "assistant")
    logger.info("Agent message: %s", message)


def user_message(call_number: str, message: str) -> None:
    """Log a message from the caller."""
    _save_message(call_number, message, "user")
    logger.info("User message: %s", message)


def ai_message(
    call_number: str,
    message: str,
    duration: float | None = None,
    model_source: str | None = None,
) -> None:
    """Log an AI/LLM response, optionally including elapsed time."""
    message_with_timing = _format_timed_message(message, duration)
    _save_message(call_number, message_with_timing, "AI", model_source)
    logger.info("AI: %s", message_with_timing)


def google_message(
    call_number: str, message: str, duration: float | None = None
) -> None:
    """Log a Google Maps API response, optionally including elapsed time."""
    message_with_timing = _format_timed_message(message, duration)
    _save_message(call_number, message_with_timing, "google")
    logger.info("Google: %s", message_with_timing)


def twilio_message(call_number: str, message: str) -> None:
    """Log a Twilio event."""
    _save_message(call_number, message, "twilio")
    logger.info("Twilio: %s", message)


def _save_message(
    call_number: str,
    message: str,
    role: str,
    model_source: str | None = None,
) -> None:
    """Append a message entry to the call-history message log."""
    start_time = _get_start_time(call_number)
    if not start_time:
        return

    key = _history_key(
        _normalize_phone(call_number), start_time, "nachrichten"
    )
    existing_messages = redis.get(key)

    if existing_messages:
        messages = _loads_json_or_yaml(existing_messages)
    else:
        messages = []

    message_entry: dict[str, str] = {"role": role, "content": message}
    if model_source:
        message_entry["model"] = model_source

    messages.append(message_entry)

    redis.set(
        key,
        json.dumps(messages, ensure_ascii=False),
    )


def save_location(call_number: str, location: dict) -> None:
    """Persist the caller's location for the active call and history."""
    redis.set(
        _active_call_key(call_number, "standort"),
        json.dumps(location, indent=2, ensure_ascii=False),
        ex=PERSISTENCE_TIME,
    )
    _set_hist_info(call_number, "Standort", location)


def get_location(call_number: str) -> dict | None:
    """Return the caller's stored location, or ``None`` if absent."""
    raw = redis.get(_active_call_key(call_number, "standort"))
    if not raw:
        return None
    return json.loads(raw.decode("utf-8"))


def get_shared_location(call_number: str) -> dict | None:
    """Return the location shared via SMS link, or ``None``."""
    location_data = redis.get(
        _active_call_key(call_number, "geteilter_standort")
    )
    if location_data:
        return json.loads(location_data.decode("utf-8"))
    return None


def add_to_caller_queue(caller: str, name: str, phone: str) -> None:
    """Add a contact to the transfer queue with name and phone."""
    queue = json.loads(
        redis.get(_active_call_key(caller, "warteschlange")) or b"[]"
    )
    queue.append({"name": name, "phone": phone})
    redis.set(
        _active_call_key(caller, "warteschlange"),
        json.dumps(queue),
        ex=PERSISTENCE_TIME,
    )
    # Save full queue info (name and phone) to history for dashboard display
    _set_hist_info(caller, "Warteschlange", queue)


def get_next_caller_in_queue(caller: str) -> dict | None:
    """Get next contact from queue. Returns {name, phone} or None."""
    queue_data = redis.get(_active_call_key(caller, "warteschlange"))
    queue = json.loads(queue_data.decode("utf-8")) if queue_data else []
    return queue[0] if queue else None


def delete_next_caller(caller: str) -> None:
    """Remove the first contact from the transfer queue."""
    queue = json.loads(
        redis.get(_active_call_key(caller, "warteschlange")) or b"[]"
    )
    if queue:
        queue.pop(0)
    redis.set(
        _active_call_key(caller, "warteschlange"),
        json.dumps(queue),
        ex=PERSISTENCE_TIME,
    )
    # Update history to reflect queue changes
    _set_hist_info(caller, "Warteschlange", queue)


def clear_caller_queue(caller: str) -> None:
    """Delete the entire transfer queue for the caller."""
    redis.delete(_active_call_key(caller, "warteschlange"))


def set_transferred_to(caller: str, phone: str, name: str = "") -> None:
    """Record which contact the call was transferred to (phone + name)."""
    redis.set(
        _active_call_key(caller, "Weitergeleitet an"),
        phone,
        ex=PERSISTENCE_TIME,
    )
    if name:
        redis.set(
            _active_call_key(caller, "Weitergeleitet an Name"),
            name,
            ex=PERSISTENCE_TIME,
        )


def get_transferred_to(caller: str) -> tuple[str, str] | None:
    """Return (phone, name) of the previous transfer contact, or None."""
    phone = redis.get(_active_call_key(caller, "Weitergeleitet an"))
    if not phone:
        return None
    name = redis.get(_active_call_key(caller, "Weitergeleitet an Name"))
    return (
        phone.decode("utf-8"),
        name.decode("utf-8") if name else "",
    )


def save_job_info(caller: str, detail_name: str, detail_value: str) -> None:
    """Persist a named piece of call metadata to both active state and history."""
    _set_hist_info(caller, detail_name, detail_value)
    redis.set(
        _active_call_key(caller, detail_name),
        detail_value,
        ex=PERSISTENCE_TIME,
    )


def delete_job_info(caller: str, detail_name: str) -> None:
    """Remove a named piece of call metadata from active state."""
    redis.delete(_active_call_key(caller, detail_name))


def get_job_info(caller: str, detail_name: str) -> str | None:
    """Retrieve a named piece of call metadata from active state."""
    detail = redis.get(_active_call_key(caller, detail_name))
    if detail:
        return detail.decode("utf-8")
    return None


def get_call_timestamp(call_number: str) -> str | None:
    """Get the timestamp for when a call was started."""
    try:
        return _get_start_time(call_number)
    except (ConnectionError, OSError) as exc:
        logger.error("Error getting call timestamp: %s", exc)
        return None


def save_call_recording(
    call_number: str,
    recording_bytes: bytes,
    content_type: str = "audio/mpeg",
    metadata: dict | None = None,
    recording_type: str | None = None,
) -> None:
    """Store a call recording as base64-encoded JSON in Redis."""
    if not call_number or not recording_bytes or call_number == "anonymous":
        return

    start_time = _get_start_time(call_number)
    if not start_time:
        return

    normalized_type = _normalize_recording_type(recording_type)
    number_without_plus = _normalize_phone(call_number)
    redis_key = _recording_key(number_without_plus, start_time, normalized_type)

    duration_info = ""
    if metadata and "duration_total_seconds" in metadata:
        duration_info = f", total_duration={metadata['duration_total_seconds']}s"

    logger.info(
        "Saving %s recording for %s with key %s (bytes=%d%s)",
        normalized_type,
        call_number,
        redis_key,
        len(recording_bytes),
        duration_info,
    )

    payload_obj: dict[str, Any] = {
        "content_type": content_type,
        "data": base64.b64encode(recording_bytes).decode("ascii"),
        "recording_type": normalized_type,
    }
    if metadata:
        payload_obj["metadata"] = metadata

    redis.set(redis_key, json.dumps(payload_obj))

    if normalized_type == DEFAULT_RECORDING_TYPE:
        save_job_info(call_number, "Audioaufnahme", "Verfügbar")
        save_job_info(call_number, "Audioaufnahme (Erstanruf)", "Verfügbar")
    else:
        save_job_info(call_number, "Audioaufnahme (SMS Rückruf)", "Verfügbar")


def get_call_recording(
    number: str, timestamp: str, recording_type: str | None = None
) -> dict | None:
    """Retrieve a stored recording payload (JSON) from Redis."""
    if not number or not timestamp:
        return None

    normalized_type = _normalize_recording_type(recording_type)
    number = _normalize_phone(number)

    redis_key = _recording_key(number, timestamp, normalized_type)
    recording_data = redis.get(redis_key)

    if not recording_data:
        return None

    try:
        payload = json.loads(recording_data.decode("utf-8"))
        payload.setdefault("recording_type", normalized_type)
        return payload
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.error(
            "Failed to load recording for %s at %s: %s", number, timestamp, exc
        )
        return None


def get_call_recording_binary(
    number: str, timestamp: str, recording_type: str | None = None
) -> tuple[bytes | None, str | None]:
    """Return decoded audio bytes and content type for a stored recording."""
    payload = get_call_recording(number, timestamp, recording_type)
    if not payload:
        return None, None

    data_field = payload.get("data")
    if not data_field:
        return None, None

    try:
        audio_bytes = base64.b64decode(data_field)
    except (ValueError, base64.binascii.Error) as exc:
        logger.error(
            "Failed to decode recording for %s at %s: %s", number, timestamp, exc
        )
        return None, None

    return audio_bytes, payload.get("content_type", "audio/mpeg")


def get_available_recordings(number: str, timestamp: str) -> dict[str, dict]:
    """Return all available recordings keyed by recording type."""
    recordings: dict[str, dict] = {}
    for recording_type in RECORDING_TYPE_ORDER:
        payload = get_call_recording(number, timestamp, recording_type)
        if payload:
            recordings[recording_type] = payload
    return recordings


def cleanup_call(call_number: str) -> None:
    """Remove transient active-call keys from Redis."""
    start_time = redis.get(_active_call_key(call_number, "gestartet_um"))
    if not start_time:
        return

    keys_to_delete = [
        _active_call_key(call_number, "gestartet_um"),
        _active_call_key(call_number, "warteschlange"),
    ]

    logger.warning(
        "Cleaning up call data for %s: %s", call_number, keys_to_delete
    )

    redis.delete(*keys_to_delete)


def set_transcription_text(
    call_number: str, transcription_text: str | None
) -> None:
    """Store the transcription text for the call."""
    save_job_info(call_number, "Transkription", transcription_text or "")


def get_transcription_text(call_number: str) -> str | None:
    """Retrieve the transcription text for the call."""
    return get_job_info(call_number, "Transkription")
