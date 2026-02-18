"""ElevenLabs text-to-speech and speech-to-text utilities with disk caching."""

import io
import logging
import os
import shutil
import time

import requests
from elevenlabs import VoiceSettings
from elevenlabs.client import ElevenLabs

# Ensure pydub can find ffmpeg before importing AudioSegment
if not shutil.which("ffmpeg"):
    _local_ffmpeg = os.path.join(os.path.expanduser("~"), "ffmpeg", "ffmpeg.exe")
    if os.path.isfile(_local_ffmpeg):
        os.environ["PATH"] += os.pathsep + os.path.dirname(_local_ffmpeg)

from pydub import AudioSegment

from twilio_agent.utils.cache import CacheManager
from twilio_agent.actions.redis_actions import set_transcription_text
from twilio_agent.settings import settings

logger = logging.getLogger("ElevenLabs")

# Initialize ElevenLabs client
_api_key = settings.env.ELEVENLABS_API_KEY.get_secret_value() if settings.env.ELEVENLABS_API_KEY else None
_elevenlabs_client = ElevenLabs(api_key=_api_key) if _api_key else None

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

    if not _elevenlabs_client:
        logger.error("ElevenLabs API key not configured")
        raise ValueError("ElevenLabs API key not configured")

    input_data = {"text": text}
    cached = cache_manager.get("generate_speech", input_data)
    if cached is not None:
        return cached, 0.0

    start_time = time.perf_counter()
    logger.info("Starting ElevenLabs TTS for text: '%s'", _truncate_for_log(text))

    try:
        response = _elevenlabs_client.text_to_speech.convert(
            voice_id=settings.env.ELEVENLABS_VOICE_ID,
            output_format="mp3_22050_32",
            language_code="de",
            text=text,
            model_id=settings.env.ELEVENLABS_TTS_MODEL,
            voice_settings=VoiceSettings(
                stability=1.0,
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
    raw_bytes = b"".join(chunks)

    # Append 0.5s silence to prevent audio cutoff
    audio = AudioSegment.from_mp3(io.BytesIO(raw_bytes))
    audio += AudioSegment.silent(duration=300)
    output = io.BytesIO()
    audio.export(output, format="mp3")
    bytes_data = output.getvalue()

    cache_manager.set("generate_speech", input_data, bytes_data, ".mp3")

    duration = time.perf_counter() - start_time
    logger.info("ElevenLabs TTS completed in %.2f seconds", duration)
    return bytes_data, duration


def transcribe_speech(redording_id: str, call_number: str) -> tuple[str, float]:
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
    twilio_account_sid_ro = settings.env.TWILIO_ACCOUNT_SID_RO
    twilio_auth_token_ro = settings.env.TWILIO_AUTH_TOKEN_RO.get_secret_value() if settings.env.TWILIO_AUTH_TOKEN_RO else None
    elevenlabs_api_key = settings.env.ELEVENLABS_API_KEY.get_secret_value() if settings.env.ELEVENLABS_API_KEY else None

    if not twilio_account_sid_ro or not twilio_auth_token_ro:
        logger.error(
            "TWILIO_ACCOUNT_SID_RO or TWILIO_AUTH_TOKEN_RO not set; "
            "cannot authenticate recording URL for transcription"
        )
        return "<Error during transcription>", 0.0

    if not elevenlabs_api_key:
        logger.error("ELEVENLABS_API_KEY not configured")
        return "<Error during transcription>", 0.0

    recording_url = _build_recording_url(redording_id)
    set_transcription_text(call_number, None)  # Clear previous transcription while processing new one

    logger.info("Fetching recording for transcription from URL: %s", recording_url)

    start_time = time.perf_counter()

    authenticated_url = (
        f"https://{twilio_account_sid_ro}:{twilio_auth_token_ro}"
        f"@{recording_url.replace('https://', '')}"
    )

    logger.info("Authenticated recording URL for ElevenLabs: %s", authenticated_url)

    data = {
        "model_id": settings.env.ELEVENLABS_STT_MODEL,
        "language_code": "deu",
        "tag_audio_events": "false",
        "cloud_storage_url": authenticated_url,
    }

    http_response = requests.post(
        settings.env.ELEVENLABS_STT_URL,
        headers={"xi-api-key": elevenlabs_api_key},
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

    set_transcription_text(call_number, text)


def _build_recording_url(recording_id: str) -> str:
    return (
        f"https://api.twilio.com/2010-04-01/Accounts/"
        f"{settings.env.TWILIO_RECORDING_ACCOUNT}/Recordings/{recording_id}"
    )