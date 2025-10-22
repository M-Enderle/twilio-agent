import json
import logging
import os
import traceback
from datetime import datetime, timedelta
from pathlib import Path

import dotenv
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel
from redis import Redis

from twilio_agent.actions.redis_actions import google_message

logger = logging.getLogger("uvicorn")

dotenv.load_dotenv()
STANDORT_URL = os.getenv("STANDORT_URL", "https://9e4c482f86de.ngrok-free.app/location")
SERVER_URL = os.getenv("SERVER_URL", "https://9e4c482f86de.ngrok-free.app")

template_dir = Path(__file__).resolve().parents[2] / "templates"
jinja_env = Environment(
    loader=FileSystemLoader(template_dir, encoding="utf-8"), autoescape=True
)

REDIS_URL = os.getenv("REDIS_URL", "redis://:${REDIS_PASSWORD}@redis:6379")
redis_client = Redis.from_url(REDIS_URL)

router = APIRouter()


class LocationData(BaseModel):
    latitude: float
    longitude: float


def generate_location_link(phone_number: str):
    """
    Generate a unique, temporary link for location sharing.

    Args:
        phone_number (str): The phone number associated with the link.

    Returns:
        dict: Contains the link ID, full URL, and expiration time.
    """
    try:
        new_id = redis_client.incr("notdienststation:standort_letzte_id")
    except Exception:
        raise HTTPException(status_code=500, detail="Error generating location link")

    link_id = str(new_id)
    expires_at = datetime.now() + timedelta(hours=24)

    link_data = {
        "status": "generated",
        "created_at": datetime.now().isoformat(),
        "expires_at": expires_at.isoformat(),
        "used": False,
        "phone_number": phone_number,
    }

    redis_client.setex(
        f"notdienststation:standort_link:{link_id}",
        int(timedelta(hours=24).total_seconds()),
        json.dumps(link_data),
    )

    link_url = f"{STANDORT_URL}/{link_id}"

    return {
        "link_id": link_id,
        "link_url": link_url,
        "expires_at": expires_at.isoformat(),
    }


@router.get("/location/{link_id}")
def get_location_page(link_id: str):
    """
    Serve the location sharing page for a specific link ID.

    Args:
        link_id (str): The unique identifier for the location sharing link.

    Returns:
        HTMLResponse: The location sharing webpage.
    """
    try:
        link_data_str = redis_client.get(f"notdienststation:standort_link:{link_id}")
        if not link_data_str:
            raise HTTPException(status_code=404, detail="Link not found or expired")

        link_data = json.loads(link_data_str)

        if link_data.get("used", False):
            raise HTTPException(status_code=410, detail="Link has already been used")

        template = jinja_env.get_template("location_sharing.html")
        html_content = template.render(link_id=link_id, server_url=SERVER_URL)
        return HTMLResponse(content=html_content)

    except HTTPException:
        raise

    except Exception:
        raise HTTPException(status_code=500, detail="Error processing location link")


@router.post("/receive-location/{link_id}")
def receive_location(link_id: str, location_data: LocationData):
    """
    Receive and store location data for a specific link ID.

    Args:
        link_id (str): The unique identifier for the location sharing link.
        location_data (LocationData): The latitude and longitude coordinates.

    Returns:
        dict: Success confirmation and stored data info.
    """
    try:
        link_data_str = redis_client.get(f"notdienststation:standort_link:{link_id}")
        if not link_data_str:
            raise HTTPException(status_code=404, detail="Link not found or expired")

        link_data = json.loads(link_data_str)

        if link_data.get("used", False):
            raise HTTPException(status_code=410, detail="Link has already been used")

        location_record = {
            "link_id": link_id,
            "latitude": location_data.latitude,
            "longitude": location_data.longitude,
            "received_at": datetime.now().isoformat(),
            "original_link_data": link_data,
        }

        redis_client.setex(
            f"notdienststation:anrufe:{link_data['phone_number']}:geteilter_standort",
            int(timedelta(hours=24).total_seconds()),
            json.dumps(location_record),
        )

        link_data["used"] = True
        link_data["used_at"] = datetime.now().isoformat()
        link_data["status"] = "used"

        redis_client.setex(
            f"notdienststation:standort_link:{link_id}", 60 * 60 * 24, json.dumps(link_data)
        )

        # Trigger outbound call to the phone number associated with the link
        from twilio_agent.actions.twilio_actions import outbound_call_after_sms

        outbound_call_after_sms(link_data["phone_number"])

        return {
            "success": True,
            "message": "Location received successfully",
            "link_id": link_id,
            "received_at": datetime.now().isoformat(),
        }

    except HTTPException as e:
        logger.error(f"HTTPException: {e}")
        logger.error(traceback.format_exc())
        raise
    except Exception as e:
        logger.error(f"Error processing location data: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Error processing location data")
