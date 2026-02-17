"""ElevenLabs text-to-speech and speech-to-text utilities with disk caching."""

import logging
import os
import time

import requests
from elevenlabs import VoiceSettings
from elevenlabs.client import ElevenLabs

from twilio_agent.utils.cache import CacheManager

logger = logging.getLogger("uvicorn")

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
TWILIO_ACCOUNT_SID_RO = os.getenv("TWILIO_ACCOUNT_SID_RO")
TWILIO_AUTH_TOKEN_RO = os.getenv("TWILIO_AUTH_TOKEN_RO")

VOICE_ID = "jccKWdITZiywXGZfLmCo"
TTS_MODEL_ID = "eleven_turbo_v2_5"
STT_MODEL_ID = "scribe_v2"
STT_API_URL = "https://api.elevenlabs.io/v1/speech-to-text"

_elevenlabs_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

cache_manager = CacheManager("audio")


def _truncate_for_log(text: str, max_length: int = 50) -> str:
    """Truncate text for log messages, appending '...' only when needed."""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."


def generate_speech(text: str) -> tuple[bytes, float]:
    """Generate MP3 audio bytes for the given German text via ElevenLabs TTS.

    Args:
        text: The German text to synthesise. Empty strings return
            immediately with empty bytes.

    Returns:
        A tuple of (mp3_bytes, generation_duration_seconds). Duration is
        ``0.0`` when the result was served from cache or the input was empty.
    """
    if not text:
        return b"", 0.0

    input_data = {"text": text}
    cached = cache_manager.get("generate_speech", input_data)
    if cached is not None:
        return cached, 0.0

    start_time = time.perf_counter()
    logger.info("Starting ElevenLabs TTS for text: '%s'", _truncate_for_log(text))

    try:
        response = _elevenlabs_client.text_to_speech.convert(
            voice_id=VOICE_ID,
            output_format="mp3_22050_32",
            language_code="de",
            text=text,
            model_id=TTS_MODEL_ID,
            voice_settings=VoiceSettings(
                stability=0.9,
                similarity_boost=0.9,
            ),
        )
    except Exception:
        logger.exception("ElevenLabs TTS request failed for text: '%s'", _truncate_for_log(text))
        raise

    chunks = []
    for chunk in response:
        if isinstance(chunk, str):
            chunk = chunk.encode()
        chunks.append(chunk)
    bytes_data = b"".join(chunks)

    cache_manager.set("generate_speech", input_data, bytes_data, ".mp3")

    duration = time.perf_counter() - start_time
    logger.info("ElevenLabs TTS completed in %.2f seconds", duration)
    return bytes_data, duration


def transcribe_speech(recording_url: str) -> tuple[str, float]:
    """Transcribe speech from a Twilio recording URL via ElevenLabs STT.

    The recording is fetched by ElevenLabs using Twilio read-only
    credentials embedded in the URL. Requires ``TWILIO_ACCOUNT_SID_RO``
    and ``TWILIO_AUTH_TOKEN_RO`` environment variables.

    Args:
        recording_url: Full HTTPS URL to a Twilio recording resource.

    Returns:
        A tuple of (transcribed_text, request_duration_seconds). On
        failure the text is ``"<Error during transcription>"``.
    """
    if not TWILIO_ACCOUNT_SID_RO or not TWILIO_AUTH_TOKEN_RO:
        logger.error(
            "TWILIO_ACCOUNT_SID_RO or TWILIO_AUTH_TOKEN_RO not set; "
            "cannot authenticate recording URL for transcription"
        )
        return "<Error during transcription>", 0.0

    start_time = time.perf_counter()
    logger.info("Starting ElevenLabs transcription for: %s", recording_url)

    authenticated_url = (
        f"https://{TWILIO_ACCOUNT_SID_RO}:{TWILIO_AUTH_TOKEN_RO}"
        f"@{recording_url.replace('https://', '')}"
    )
    data = {
        "model_id": STT_MODEL_ID,
        "language_code": "deu",
        "tag_audio_events": "false",
        "cloud_storage_url": authenticated_url,
    }

    http_response = requests.post(
        STT_API_URL,
        headers={"xi-api-key": ELEVENLABS_API_KEY},
        data=data,
        timeout=30,
    )

    if http_response.status_code != 200:
        logger.error(
            "ElevenLabs transcription failed (HTTP %d): %s",
            http_response.status_code,
            http_response.text,
        )
        return "<Error during transcription>", 0.0

    text = http_response.json().get("text", "")
    duration = time.perf_counter() - start_time
    logger.info(
        "ElevenLabs transcription completed in %.2f seconds, text: '%s'",
        duration,
        _truncate_for_log(text),
    )
    return text, duration
