import logging
import os
import time

import requests
from dotenv import load_dotenv
from elevenlabs import VoiceSettings
from elevenlabs.client import ElevenLabs

from twilio_agent.utils.cache import CacheManager

load_dotenv()

logger = logging.getLogger("uvicorn")

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID_RO")
AUTH = os.getenv("TWILIO_AUTH_TOKEN_RO")
elevenlabs = ElevenLabs(
    api_key=ELEVENLABS_API_KEY,
)

cache_manager = CacheManager("audio")


def generate_speech(text: str) -> tuple[bytes, float]:
    """Generate full MP3 bytes for the given text using ElevenLabs TTS."""
    if not text:
        return b"", 0.0

    input_data = {"text": text}
    cached = cache_manager.get("generate_speech", input_data)
    if cached is not None:
        return cached, 0.0

    start_time = time.time()
    logger.info(f"Starting ElevenLabs TTS for text: '{text[:50]}...'")

    response = elevenlabs.text_to_speech.convert(
        voice_id="jccKWdITZiywXGZfLmCo",
        output_format="mp3_22050_32",
        language_code="de",
        text=text,
        model_id="eleven_turbo_v2_5",
        voice_settings=VoiceSettings(
            stability=0.9,
            similarity_boost=0.9,
        ),
    )

    bytes_data = b""
    for chunk in response:
        if isinstance(chunk, str):
            chunk = chunk.encode()
        bytes_data += chunk

    cache_manager.set("generate_speech", input_data, bytes_data, ".mp3")

    duration = time.time() - start_time
    logger.info(f"ElevenLabs TTS completed in {duration:.2f} seconds")
    return bytes_data, duration


def transcribe_speech(recording_url: str) -> tuple[str, float]:
    """Transcribe speech from a given recording URL using ElevenLabs ASR."""
    url = "https://api.elevenlabs.io/v1/speech-to-text"
    start_time = time.time()
    logger.info(f"Starting ElevenLabs transcription for recording URL: {recording_url}")
    data = {
        "model_id": "scribe_v2",
        "language_code": "deu",
        "tag_audio_events": "false",
        "cloud_storage_url": f"https://{ACCOUNT_SID}:{AUTH}@{recording_url.replace('https://','')}",
    }
    logger.info("Sending transcription request to ElevenLabs")
    result = requests.post(
        url, headers={"xi-api-key": ELEVENLABS_API_KEY}, data=data, timeout=30
    )
    if result.status_code != 200:
        logger.error(f"ElevenLabs transcription failed: {result.text}")
        return "<Error during transcription>", 0.0
    text = result.json().get("text", "")
    duration = time.time() - start_time
    logger.info(
        f"ElevenLabs transcription completed in {duration:.2f} seconds, text: '{text[:50]}...'"
    )
    return text, duration


if __name__ == "__main__":
    sample_text = "Hallo, dies ist ein Test der ElevenLabs Text-zu-Sprache API."
    audio_bytes, gen_duration = generate_speech(sample_text)
    with open("sample_output.mp3", "wb") as f:
        f.write(audio_bytes)
    logger.info(
        f"Generated audio saved to 'sample_output.mp3', generation took {gen_duration:.2f} seconds."
    )
