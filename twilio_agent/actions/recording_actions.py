import asyncio
import logging
import os

import dotenv
import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from twilio.rest import Client

from twilio_agent.actions.redis_actions import (
    get_call_recording,
    get_call_recording_binary,
    get_call_timestamp,
    save_call_recording,
)

import io
import wave


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
    recording_sid = form_data.get("RecordingSid")
    segment_duration = form_data.get("RecordingDuration")
    try:
        segment_duration = int(segment_duration) if segment_duration is not None else None
    except Exception:
        segment_duration = None
    if recording_url and form_data.get("RecordingStatus") == "completed":

        # Determine existing content type to choose best format
        timestamp = get_call_timestamp(original_caller)
        existing_content_type = None
        if timestamp:
            previous_payload = get_call_recording(original_caller, timestamp)
            if previous_payload and isinstance(previous_payload, dict):
                existing_content_type = previous_payload.get("content_type")

        # Prefer consistent format: if existing is mp3 -> download mp3; else use wav
        desired_format = "mp3" if (existing_content_type or "").startswith("audio/mpeg") else "wav"
        media_url = recording_url.replace(".json", f".{desired_format}")
        logger.info(
            "Downloading recording %s from %s for caller %s (segment_duration=%ss, chosen_format=%s, existing_ctype=%s)",
            recording_sid,
            media_url,
            original_caller,
            segment_duration,
            desired_format,
            existing_content_type,
        )

        # Download the recording using Twilio credentials
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")

        async with httpx.AsyncClient() as client:
            response = await client.get(media_url, auth=(account_sid, auth_token))

            if response.status_code == 200:
                new_data = response.content
                # Twilio may not set header; default according to desired format
                default_ctype = "audio/mpeg" if desired_format == "mp3" else "audio/wav"
                content_type = response.headers.get("Content-Type", default_ctype)
                logger.info(
                    "Downloaded new recording %s of size %d bytes for %s (ctype=%s)",
                    recording_sid,
                    len(new_data),
                    original_caller,
                    content_type,
                )

                # Check if a recording already exists and append to it
                logger.info("Got timestamp %s for %s", timestamp, original_caller)
                if timestamp:
                    # Load previous payload to retrieve metadata
                    previous_payload = get_call_recording(original_caller, timestamp)
                    prev_total = None
                    if previous_payload and isinstance(previous_payload, dict):
                        prev_meta = previous_payload.get("metadata") or {}
                        prev_total = prev_meta.get("duration_total_seconds")
                    if prev_total is not None:
                        logger.info(
                            "Previous total duration for %s at %s: %ss",
                            original_caller,
                            timestamp,
                            prev_total,
                        )
                    existing_audio, existing_content_type = get_call_recording_binary(
                        original_caller, timestamp
                    )
                    if existing_audio:
                        logger.info(
                            "Existing recording size: %d bytes for %s (ctype=%s)",
                            len(existing_audio),
                            original_caller,
                            existing_content_type,
                        )
                        if (existing_content_type or "").startswith("audio/wav") and content_type.startswith("audio/wav"):
                            try:
                                # Concatenate WAV safely by stitching frames
                                with io.BytesIO(existing_audio) as exb, io.BytesIO(new_data) as nwb:
                                    with wave.open(exb, "rb") as exw, wave.open(nwb, "rb") as nww:
                                        ex_params = (exw.getnchannels(), exw.getsampwidth(), exw.getframerate())
                                        nw_params = (nww.getnchannels(), nww.getsampwidth(), nww.getframerate())
                                        logger.info(
                                            "WAV params prev=%s new=%s for %s",
                                            ex_params,
                                            nw_params,
                                            original_caller,
                                        )
                                        if ex_params != nw_params:
                                            logger.warning(
                                                "WAV params mismatch; falling back to raw append (may be invalid)"
                                            )
                                            recording_data = existing_audio + new_data
                                        else:
                                            with io.BytesIO() as outb:
                                                with wave.open(outb, "wb") as outw:
                                                    outw.setnchannels(exw.getnchannels())
                                                    outw.setsampwidth(exw.getsampwidth())
                                                    outw.setframerate(exw.getframerate())
                                                    exw.rewind()
                                                    nww.rewind()
                                                    outw.writeframes(exw.readframes(exw.getnframes()))
                                                    outw.writeframes(nww.readframes(nww.getnframes()))
                                                recording_data = outb.getvalue()
                                            content_type = "audio/wav"
                                            logger.info(
                                                "WAV concatenation successful for %s (bytes_total=%d)",
                                                original_caller,
                                                len(recording_data),
                                            )
                            except Exception as exc:
                                logger.exception("Failed WAV concat; falling back to raw append: %s", exc)
                                recording_data = existing_audio + new_data
                        else:
                            # mp3 path or mismatched: try to stay consistent with existing
                            if (existing_content_type or "").startswith("audio/mpeg") and content_type.startswith("audio/mpeg"):
                                recording_data = existing_audio + new_data
                                content_type = "audio/mpeg"
                                logger.info("MP3 byte-append used for %s (bytes_total=%d)", original_caller, len(recording_data))
                            else:
                                logger.warning("Content-type mismatch (prev=%s, new=%s); using raw append", existing_content_type, content_type)
                                recording_data = existing_audio + new_data
                        logger.info("Combined recording size: %d bytes for %s", len(recording_data), original_caller)
                    else:
                        recording_data = new_data
                        logger.info("No existing recording, using new one of size %d bytes for %s", len(recording_data), original_caller)
                else:
                    recording_data = new_data
                    logger.info("No timestamp, storing new recording of size %d bytes for %s", len(recording_data), original_caller)

                # Compute total duration metadata
                total_seconds = None
                if timestamp:
                    total_seconds = (prev_total or 0) + (segment_duration or 0)
                else:
                    total_seconds = segment_duration or 0
                metadata = {
                    "duration_total_seconds": total_seconds,
                    "last_segment_seconds": segment_duration,
                    "recording_sid": recording_sid,
                    "bytes_last_segment": len(new_data),
                    "bytes_total": len(recording_data),
                }

                logger.info(
                    "Storing recording for %s (segments_total=%ss, last_segment=%ss, bytes_total=%d)",
                    original_caller,
                    total_seconds,
                    segment_duration,
                    len(recording_data),
                )

                save_call_recording(original_caller, recording_data, content_type, metadata)
                logger.info("Saved combined recording for %s (total_duration=%ss)", original_caller, total_seconds)
            else:
                logger.error(
                    "Failed to download recording %s for %s. Status: %s",
                    recording_sid,
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
