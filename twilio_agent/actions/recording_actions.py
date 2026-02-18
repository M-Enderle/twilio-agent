"""Twilio call recording lifecycle management.

Handles starting recordings on active calls, processing Twilio recording
status callbacks (download and persist to Redis), and serving stored
recordings to the dashboard with HTTP range-request support.
"""

import asyncio
import logging
import os

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

from twilio_agent.actions.redis_actions import (
    get_call_recording_binary,
    get_call_timestamp,
    save_call_recording,
)

_account_sid = os.getenv("TWILIO_ACCOUNT_SID")
_auth_token = os.getenv("TWILIO_AUTH_TOKEN")
_server_url = os.getenv("SERVER_URL")

_twilio_client = Client(_account_sid, _auth_token)

router = APIRouter()

logger = logging.getLogger("uvicorn")

_MAX_RECORDING_RETRIES = 3


def _encode_phone(number: str) -> str:
    """Replace leading '+' with '00' for URL-safe phone representation."""
    return number.replace("+", "00")


def _decode_phone(encoded: str) -> str:
    """Restore a '00'-prefixed phone number back to '+' format."""
    if encoded and encoded.startswith("00"):
        return "+" + encoded[2:]
    return encoded


async def start_recording(call_sid: str, caller: str) -> None:
    """Start a Twilio recording on the given call with retry logic.

    Args:
        call_sid: The Twilio call SID to record.
        caller: The caller's phone number (E.164 format).
    """
    for attempt in range(_MAX_RECORDING_RETRIES):
        try:
            await asyncio.sleep(2)
            recording = _twilio_client.calls(call_sid).recordings.create(
                recording_status_callback=(
                    f"{_server_url}/recording-status-callback/"
                    f"{_encode_phone(caller)}?source=initial"
                ),
                recording_status_callback_event="completed",
            )
            logger.info(
                "Started recording for call %s: %s", call_sid, recording.sid
            )
            break
        except TwilioRestException as e:
            if attempt == _MAX_RECORDING_RETRIES - 1:
                logger.error(
                    "Failed to start recording after %d attempts: %s",
                    _MAX_RECORDING_RETRIES,
                    e,
                )
            else:
                logger.warning(
                    "Attempt %d failed: %s. Retrying...", attempt + 1, e
                )
                await asyncio.sleep(1)


def _parse_segment_duration(raw_value: str | None) -> int | None:
    """Safely parse the segment duration from form data."""
    if raw_value is None:
        return None
    try:
        return int(raw_value)
    except (ValueError, TypeError):
        return None


@router.api_route(
    "/recording-status-callback/{caller}", methods=["GET", "POST"]
)
async def recording_status_callback(
    request: Request, caller: str
) -> JSONResponse:
    """Handle Twilio recording status webhook.

    Downloads the completed recording and persists it to Redis.

    Args:
        request: The incoming FastAPI request.
        caller: URL-encoded caller phone number ('00' prefix).

    Returns:
        JSON acknowledgement response.
    """
    form_data = await request.form()
    original_caller = _decode_phone(caller)

    recording_url = form_data.get("RecordingUrl")
    recording_sid = form_data.get("RecordingSid")
    segment_duration = _parse_segment_duration(
        form_data.get("RecordingDuration")
    )

    if not (recording_url and form_data.get("RecordingStatus") == "completed"):
        return JSONResponse(content={"status": "ok"})

    timestamp = get_call_timestamp(original_caller)
    recording_type = (
        request.query_params.get("source") or "initial"
    ).lower()
    if recording_type not in {"initial", "followup"}:
        logger.warning(
            "Unknown recording source '%s' for caller %s; "
            "defaulting to 'initial'",
            recording_type,
            original_caller,
        )
        recording_type = "initial"

    desired_format = "mp3"
    media_url = recording_url.replace(".json", f".{desired_format}")
    logger.info(
        "Downloading %s recording %s from %s for caller %s "
        "(segment_duration=%ss)",
        recording_type,
        recording_sid,
        media_url,
        original_caller,
        segment_duration,
    )

    async with httpx.AsyncClient() as http_client:
        response = await http_client.get(
            media_url, auth=(_account_sid, _auth_token)
        )

        if response.status_code == 200:
            recording_data = response.content
            default_ctype = (
                "audio/mpeg" if desired_format == "mp3" else "audio/wav"
            )
            content_type = response.headers.get(
                "Content-Type", default_ctype
            )
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


def _common_headers() -> dict[str, str]:
    """Return headers shared by all recording responses."""
    return {
        "Accept-Ranges": "bytes",
        "Cache-Control": "public, max-age=3600",
        "Access-Control-Allow-Origin": "*",
    }


def _build_recording_response_with_range(
    number: str,
    timestamp: str,
    recording_type: str,
    request: Request,
) -> Response:
    """Build a response serving a stored recording with HTTP range support.

    Args:
        number: The caller phone number.
        timestamp: The call timestamp key.
        recording_type: Either 'initial' or 'followup'.
        request: The incoming request (inspected for Range header).

    Returns:
        A full or partial (206) audio response.
    """
    audio_bytes, content_type = get_call_recording_binary(
        number, timestamp, recording_type
    )
    if not audio_bytes:
        raise HTTPException(
            status_code=404, detail="Recording not found"
        )

    file_size = len(audio_bytes)
    range_header = request.headers.get("range")

    if range_header:
        try:
            range_spec = range_header.replace("bytes=", "").split("-")
            start = int(range_spec[0]) if range_spec[0] else 0
            end = (
                int(range_spec[1])
                if len(range_spec) > 1 and range_spec[1]
                else file_size - 1
            )
        except (ValueError, IndexError):
            return Response(status_code=416)

        start = max(0, min(start, file_size - 1))
        end = max(start, min(end, file_size - 1))

        chunk = audio_bytes[start : end + 1]
        headers = _common_headers()
        headers.update(
            {
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Content-Length": str(len(chunk)),
                "Access-Control-Expose-Headers": (
                    "Content-Range, Accept-Ranges, Content-Length"
                ),
            }
        )

        return Response(
            content=chunk,
            status_code=206,
            media_type=content_type,
            headers=headers,
        )

    headers = _common_headers()
    headers.update(
        {
            "Content-Length": str(file_size),
            "Access-Control-Expose-Headers": (
                "Accept-Ranges, Content-Length"
            ),
        }
    )

    return Response(
        content=audio_bytes,
        media_type=content_type,
        headers=headers,
    )


@router.get("/recordings/{number}/{timestamp}")
async def fetch_initial_recording(
    number: str, timestamp: str, request: Request
) -> Response:
    """Serve the initial call recording with range-request support."""
    return _build_recording_response_with_range(
        number, timestamp, "initial", request
    )


@router.get("/recordings/link/{number}/{timestamp}")
async def fetch_followup_recording(
    number: str, timestamp: str, request: Request
) -> Response:
    """Serve the follow-up (SMS callback) recording with range support."""
    return _build_recording_response_with_range(
        number, timestamp, "followup", request
    )
