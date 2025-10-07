import asyncio
import logging
import os

import dotenv
import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from twilio.rest import Client

from twilio_agent.actions.redis_actions import (get_call_recording_binary,
                                                get_call_timestamp,
                                                save_call_recording)

dotenv.load_dotenv()

account_sid = os.getenv("TWILIO_ACCOUNT_SID")
auth_token = os.getenv("TWILIO_AUTH_TOKEN")
server_url = os.getenv("SERVER_URL")

client = Client(account_sid, auth_token)

router = APIRouter()

logger = logging.getLogger("uvicorn")


async def start_recording(call_sid: str, caller: str):
    await asyncio.sleep(2)

    recording = client.calls(call_sid).recordings.create(
        recording_status_callback=server_url
        + f"/recording-status-callback/{caller.replace('+', '00')}",
        recording_status_callback_event="completed",
    )
    logger.info(f"Started recording for call {call_sid}: {recording.sid}")


@router.api_route("/recording-status-callback/{caller}", methods=["GET", "POST"])
async def recording_status_callback(request: Request, caller: str):
    form_data = await request.form()
    original_caller = caller
    if caller and caller.startswith("00"):
        original_caller = "+" + caller[2:]

    recording_url = form_data.get("RecordingUrl")
    if recording_url and form_data.get("RecordingStatus") == "completed":

        media_url = recording_url.replace(".json", ".mp3")
        logger.info("Downloading recording from %s", media_url)

        # Download the recording using Twilio credentials
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")

        async with httpx.AsyncClient() as client:
            response = await client.get(media_url, auth=(account_sid, auth_token))

            if response.status_code == 200:
                recording_data = response.content
                content_type = response.headers.get("Content-Type", "audio/mpeg")

                # Check if a recording already exists and append to it
                timestamp = get_call_timestamp(original_caller)
                if timestamp:
                    existing_audio, existing_content_type = get_call_recording_binary(
                        original_caller, timestamp
                    )
                    if existing_audio:
                        recording_data = existing_audio + recording_data
                        logger.info(
                            "Appending to existing recording for %s (existing: %d bytes, new: %d bytes, total: %d bytes)",
                            original_caller,
                            len(existing_audio),
                            len(response.content),
                            len(recording_data),
                        )
                    else:
                        logger.info(
                            "Recording downloaded and stored for %s (%d bytes)",
                            original_caller,
                            len(recording_data),
                        )
                else:
                    logger.info(
                        "Recording downloaded and stored for %s (%d bytes)",
                        original_caller,
                        len(recording_data),
                    )

                save_call_recording(original_caller, recording_data, content_type)
            else:
                logger.error(
                    "Failed to download recording for %s. Status: %s",
                    original_caller,
                    response.status_code,
                )

    return JSONResponse(content={"status": "ok"})


@router.get("/recordings/{number}/{timestamp}")
async def fetch_recording(number: str, timestamp: str):
    audio_bytes, content_type = get_call_recording_binary(number, timestamp)
    if not audio_bytes:
        raise HTTPException(status_code=404, detail="Recording not found")

    return Response(content=audio_bytes, media_type=content_type)
