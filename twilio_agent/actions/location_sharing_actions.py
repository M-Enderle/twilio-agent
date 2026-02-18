"""Location sharing endpoints for SMS-based geolocation flow.

Generates temporary links that callers receive via SMS, serves the
location-sharing web page, and ingests the coordinates the caller submits.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel, Field
from redis import Redis

logger = logging.getLogger("uvicorn")

STANDORT_URL = os.getenv("STANDORT_URL")
SERVER_URL = os.getenv("SERVER_URL")

template_dir = Path(__file__).resolve().parents[2] / "templates"
jinja_env = Environment(
    loader=FileSystemLoader(template_dir, encoding="utf-8"), autoescape=True
)

REDIS_URL = os.getenv("REDIS_URL")
redis_client = Redis.from_url(REDIS_URL)

_LINK_KEY_PREFIX = "notdienststation:standort_link"
_LINK_TTL_SECONDS = int(timedelta(hours=24).total_seconds())

router = APIRouter()


class LocationData(BaseModel):
    """Latitude/longitude pair submitted by the caller's browser."""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


def _get_valid_link_data(link_id: str) -> dict:
    """Fetch and validate a location-sharing link from Redis.

    Args:
        link_id: The unique identifier for the location sharing link.

    Returns:
        The parsed link data dictionary.

    Raises:
        HTTPException: 404 if the link does not exist or has expired,
            410 if it has already been used.
    """
    link_data_str = redis_client.get(f"{_LINK_KEY_PREFIX}:{link_id}")
    if not link_data_str:
        raise HTTPException(
            status_code=404, detail="Link not found or expired"
        )

    link_data = json.loads(link_data_str)

    if link_data.get("used", False):
        raise HTTPException(
            status_code=410, detail="Link has already been used"
        )

    return link_data


def generate_location_link(phone_number: str) -> dict:
    """Generate a unique, temporary link for location sharing.

    Args:
        phone_number: The phone number associated with the link.

    Returns:
        A dict containing the link ID, full URL, and expiration time.
    """
    try:
        new_id = redis_client.incr("notdienststation:standort_letzte_id")
    except Exception:
        raise HTTPException(
            status_code=500, detail="Error generating location link"
        )

    link_id = str(new_id)
    now = datetime.now()
    expires_at = now + timedelta(hours=24)

    link_data = {
        "status": "generated",
        "created_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "used": False,
        "phone_number": phone_number,
    }

    redis_client.setex(
        f"{_LINK_KEY_PREFIX}:{link_id}",
        _LINK_TTL_SECONDS,
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
    """Serve the location sharing page for a specific link ID.

    Args:
        link_id: The unique identifier for the location sharing link.

    Returns:
        HTMLResponse with the location sharing webpage.
    """
    try:
        _get_valid_link_data(link_id)

        template = jinja_env.get_template("location_sharing.html")
        html_content = template.render(
            link_id=link_id, server_url=SERVER_URL
        )
        return HTMLResponse(content=html_content)

    except HTTPException:
        raise

    except Exception:
        raise HTTPException(
            status_code=500, detail="Error processing location link"
        )


@router.post("/receive-location/{link_id}")
def receive_location(link_id: str, location_data: LocationData):
    """Receive and store location data for a specific link ID.

    Args:
        link_id: The unique identifier for the location sharing link.
        location_data: The latitude and longitude coordinates.

    Returns:
        A dict with success confirmation and stored data info.
    """
    try:
        link_data = _get_valid_link_data(link_id)
        now = datetime.now()

        location_record = {
            "link_id": link_id,
            "latitude": location_data.latitude,
            "longitude": location_data.longitude,
            "received_at": now.isoformat(),
            "original_link_data": link_data,
        }

        redis_client.setex(
            f"notdienststation:anrufe:{link_data['phone_number']}:geteilter_standort",
            _LINK_TTL_SECONDS,
            json.dumps(location_record),
        )

        link_data["used"] = True
        link_data["used_at"] = now.isoformat()
        link_data["status"] = "used"

        redis_client.setex(
            f"{_LINK_KEY_PREFIX}:{link_id}",
            _LINK_TTL_SECONDS,
            json.dumps(link_data),
        )

        # Deferred import: twilio_actions imports generate_location_link
        # from this module, creating a circular dependency at top level.
        from twilio_agent.actions.twilio_actions import outbound_call_after_sms

        outbound_call_after_sms(link_data["phone_number"])

        return {
            "success": True,
            "message": "Location received successfully",
            "link_id": link_id,
            "received_at": now.isoformat(),
        }

    except HTTPException as exc:
        logger.warning("HTTPException in receive_location: %s", exc.detail)
        raise
    except Exception as exc:
        logger.error("Error processing location data: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500, detail="Error processing location data"
        )
