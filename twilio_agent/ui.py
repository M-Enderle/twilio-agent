import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

import yaml
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from redis import Redis

from twilio_agent.actions.redis_actions import get_call_recording

router = APIRouter()


TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR, encoding="utf-8"),
    autoescape=select_autoescape(["html", "xml"]),
    enable_async=False,
)

REDIS_URL = os.getenv("REDIS_URL", "redis://:${REDIS_PASSWORD}@redis:6379")
redis = Redis.from_url(REDIS_URL)


@router.get("/details/{number}/{timestamp}", response_class=HTMLResponse)
def details(number: str, timestamp: str):
    # Just return the HTML template without Jinja data
    return jinja_env.get_template("details.html").render(
        number=number, timestamp=timestamp
    )


@router.websocket("/ws/details/{number}/{timestamp}")
async def websocket_details(websocket: WebSocket, number: str, timestamp: str):
    await websocket.accept()

    try:
        while True:
            # Get current data from Redis
            redis_info = redis.get(f"verlauf:{number}:{timestamp}:info")
            redis_messages = redis.get(f"verlauf:{number}:{timestamp}:nachrichten")

            if redis_info:
                info_raw = yaml.safe_load(redis_info.decode("utf-8"))

                # Convert list of dicts to single dict
                info = {}
                if isinstance(info_raw, list):
                    for item in info_raw:
                        if isinstance(item, dict):
                            info.update(item)
                else:
                    info = info_raw

                messages = (
                    yaml.safe_load(redis_messages.decode("utf-8"))
                    if redis_messages
                    else []
                )

                # Check for recording
                recording = get_call_recording(number, timestamp)
                if recording:
                    recording['number'] = number
                    recording['timestamp'] = timestamp

                # Send data to client
                data = {
                    "info": info,
                    "messages": messages,
                    "recording": recording,
                    "timestamp": datetime.now().isoformat(),
                }
                await websocket.send_json(data)
            else:
                # Send error if no data found
                await websocket.send_json(
                    {"error": "No data found", "timestamp": datetime.now().isoformat()}
                )

            # Wait 1 second before next update
            await asyncio.sleep(1)

    except WebSocketDisconnect:
        pass
