import asyncio
import logging
import os

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

from twilio_agent.actions.redis_actions import (get_call_recording_binary,
                                                get_call_timestamp,
                                                save_call_recording)

account_sid = os.getenv("TWILIO_ACCOUNT_SID")
auth_token = os.getenv("TWILIO_AUTH_TOKEN")
server_url = os.getenv("SERVER_URL")

client = Client(account_sid, auth_token)

router = APIRouter()

logger = logging.getLogger("uvicorn")


async def start_recording(call_sid: str, caller: str):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            await asyncio.sleep(2)
            recording = client.calls(call_sid).recordings.create(
                recording_status_callback=server_url
                + f"/recording-status-callback/{caller.replace('+', '00')}?source=initial",
                recording_status_callback_event="completed",
            )
            logger.info(f"Started recording for call {call_sid}: {recording.sid}")
            break  # Success, exit loop
        except TwilioRestException as e:
            if attempt == max_retries - 1:
                logger.error(
                    f"Failed to start recording after {max_retries} attempts: {e}"
                )
            else:
                logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying...")
                await asyncio.sleep(1)  # Optional delay between retries


@router.api_route("/recording-status-callback/{caller}", methods=["GET", "POST"])
async def recording_status_callback(request: Request, caller: str):
    form_data = await request.form()
    original_caller = caller
    if caller and caller.startswith("00"):
        original_caller = "+" + caller[2:]

    recording_url = form_data.get("RecordingUrl")
    recording_sid = form_data.get("RecordingSid")
    segment_duration = form_data.get("RecordingDuration")
    try:
        segment_duration = (
            int(segment_duration) if segment_duration is not None else None
        )
    except Exception:
        segment_duration = None
    if recording_url and form_data.get("RecordingStatus") == "completed":

        timestamp = get_call_timestamp(original_caller)
        recording_type = (request.query_params.get("source") or "initial").lower()
        if recording_type not in {"initial", "followup"}:
            logger.warning(
                "Unknown recording source '%s' for caller %s; defaulting to 'initial'",
                recording_type,
                original_caller,
            )
            recording_type = "initial"

        desired_format = "mp3"
        media_url = recording_url.replace(".json", f".{desired_format}")
        logger.info(
            "Downloading %s recording %s from %s for caller %s (segment_duration=%ss)",
            recording_type,
            recording_sid,
            media_url,
            original_caller,
            segment_duration,
        )

        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")

        async with httpx.AsyncClient() as client:
            response = await client.get(media_url, auth=(account_sid, auth_token))

            if response.status_code == 200:
                recording_data = response.content
                default_ctype = "audio/mpeg" if desired_format == "mp3" else "audio/wav"
                content_type = response.headers.get("Content-Type", default_ctype)
                metadata = {
                    "recording_sid": recording_sid,
                    "recording_type": recording_type,
                    "bytes_total": len(recording_data),
                    "segment_duration_seconds": segment_duration,
                    "call_timestamp": timestamp,
                }

                save_call_recording(
                    original_caller,
                    recording_data,
                    content_type,
                    metadata,
                    recording_type=recording_type,
                )
                logger.info(
                    "Saved %s recording for %s (bytes=%d, content_type=%s)",
                    recording_type,
                    original_caller,
                    len(recording_data),
                    content_type,
                )
            else:
                logger.error(
                    "Failed to download recording %s for %s. Status: %s",
                    recording_sid,
                    original_caller,
                    response.status_code,
                )

    return JSONResponse(content={"status": "ok"})


def _build_recording_response(number: str, timestamp: str, recording_type: str):
    audio_bytes, content_type = get_call_recording_binary(
        number, timestamp, recording_type
    )
    if not audio_bytes:
        raise HTTPException(status_code=404, detail="Recording not found")

    # Add headers needed for audio playback in browsers
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(len(audio_bytes)),
        "Cache-Control": "public, max-age=3600",
        "Access-Control-Allow-Origin": "*",
    }

    return Response(
        content=audio_bytes,
        media_type=content_type,
        headers=headers
    )


def _build_recording_response_with_range(number: str, timestamp: str, recording_type: str, request: Request):
    """Build response with support for HTTP range requests (needed for audio seeking)."""
    audio_bytes, content_type = get_call_recording_binary(
        number, timestamp, recording_type
    )
    if not audio_bytes:
        raise HTTPException(status_code=404, detail="Recording not found")

    file_size = len(audio_bytes)
    range_header = request.headers.get("range")

    # Handle range requests
    if range_header:
        # Parse range header (e.g., "bytes=0-1023")
        range_match = range_header.replace("bytes=", "").split("-")
        start = int(range_match[0]) if range_match[0] else 0
        end = int(range_match[1]) if len(range_match) > 1 and range_match[1] else file_size - 1

        # Ensure valid range
        start = max(0, min(start, file_size - 1))
        end = max(start, min(end, file_size - 1))

        chunk = audio_bytes[start : end + 1]
        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(len(chunk)),
            "Cache-Control": "public, max-age=3600",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Expose-Headers": "Content-Range, Accept-Ranges, Content-Length",
        }

        return Response(
            content=chunk,
            status_code=206,  # Partial Content
            media_type=content_type,
            headers=headers
        )

    # Full file response
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
        "Cache-Control": "public, max-age=3600",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Expose-Headers": "Accept-Ranges, Content-Length",
    }

    return Response(
        content=audio_bytes,
        media_type=content_type,
        headers=headers
    )


@router.get("/recordings/{number}/{timestamp}")
async def fetch_initial_recording(number: str, timestamp: str, request: Request):
    return _build_recording_response_with_range(number, timestamp, "initial", request)


@router.get("/recordings/link/{number}/{timestamp}")
async def fetch_followup_recording(number: str, timestamp: str, request: Request):
    return _build_recording_response_with_range(number, timestamp, "followup", request)
