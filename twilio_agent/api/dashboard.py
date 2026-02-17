"""Dashboard API for managing contacts and settings."""

import hashlib
import json
import logging
import uuid
from typing import Optional

import yaml
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from twilio_agent.api.auth_middleware import require_auth
from twilio_agent.settings import (
    settings,
    VALID_SERVICES,
    PhoneNumber,
    EmergencyContact,
    DirectForwarding,
    ActiveHours,
    Pricing,
    Announcements,
    Location,
    LocationContact,
)
from twilio_agent.utils.location_utils import get_geocode_result
from twilio_agent.actions.redis_actions import (
    redis,
    get_available_recordings,
    get_call_recording_binary,
)

logger = logging.getLogger("uvicorn")

router = APIRouter(dependencies=[Depends(require_auth)])


def _validate_service(service_id: str):
    if service_id not in VALID_SERVICES:
        raise HTTPException(status_code=400, detail=f"Invalid service: {service_id}")


# ── Pydantic models ────────────────────────────────────────────────

class ReorderRequest(BaseModel):
    ids: list[str]


class GeocodeRequest(BaseModel):
    address: str


# ── Locations (/services/{service_id}/locations) ──────────────────

@router.get("/services/{service_id}/locations")
async def get_locations(service_id: str):
    _validate_service(service_id)
    return settings.service(service_id).locations


@router.post("/services/{service_id}/locations", status_code=201)
async def create_location(service_id: str, body: Location):
    _validate_service(service_id)
    # Ensure ID
    if not body.id:
        body.id = str(uuid.uuid4())

    svc = settings.service(service_id)
    locations = svc.locations
    locations.append(body)
    svc.locations = locations
    return body


@router.put("/services/{service_id}/locations/reorder")
async def reorder_locations(service_id: str, body: ReorderRequest):
    _validate_service(service_id)
    svc = settings.service(service_id)
    locations = svc.locations

    # Map by ID
    by_id = {loc.id: loc for loc in locations}
    reordered = []

    # Add in requested order
    for rid in body.ids:
        if rid in by_id:
            reordered.append(by_id[rid])

    # Append any remaining not in the list
    seen = set(body.ids)
    for loc in locations:
        if loc.id not in seen:
            reordered.append(loc)

    svc.locations = reordered
    return reordered


@router.put("/services/{service_id}/locations/{location_id}")
async def update_location(service_id: str, location_id: str, body: Location):
    _validate_service(service_id)
    svc = settings.service(service_id)
    locations = svc.locations

    for i, loc in enumerate(locations):
        if loc.id == location_id:
            # Update fields, preserving ID
            body.id = location_id
            locations[i] = body
            svc.locations = locations
            return body

    raise HTTPException(status_code=404, detail="Location not found")


@router.delete("/services/{service_id}/locations/{location_id}")
async def delete_location(service_id: str, location_id: str):
    _validate_service(service_id)
    svc = settings.service(service_id)
    locations = svc.locations

    # Filter out
    new_locations = [loc for loc in locations if loc.id != location_id]

    if len(new_locations) == len(locations):
        raise HTTPException(status_code=404, detail="Location not found")

    svc.locations = new_locations
    return {"status": "deleted"}


# ── Settings (/services/{service_id}/settings/*) ──────────────────

@router.get("/services/{service_id}/settings/phone-number")
async def get_phone_number(service_id: str):
    _validate_service(service_id)
    return settings.service(service_id).phone_number


@router.put("/services/{service_id}/settings/phone-number")
async def update_phone_number(service_id: str, body: PhoneNumber):
    _validate_service(service_id)
    settings.service(service_id).phone_number = body
    return body


@router.get("/services/{service_id}/settings/emergency-contact")
async def get_emergency_contact(service_id: str):
    _validate_service(service_id)
    return settings.service(service_id).emergency_contact


@router.put("/services/{service_id}/settings/emergency-contact")
async def update_emergency_contact(service_id: str, body: EmergencyContact):
    _validate_service(service_id)
    settings.service(service_id).emergency_contact = body
    return body


@router.get("/services/{service_id}/settings/direct-forwarding")
async def get_direct_forwarding(service_id: str):
    _validate_service(service_id)
    return settings.service(service_id).direct_forwarding


@router.put("/services/{service_id}/settings/direct-forwarding")
async def update_direct_forwarding(service_id: str, body: DirectForwarding):
    _validate_service(service_id)
    settings.service(service_id).direct_forwarding = body
    return body


@router.get("/services/{service_id}/settings/active-hours")
async def get_active_hours(service_id: str):
    _validate_service(service_id)
    return settings.service(service_id).active_hours


@router.put("/services/{service_id}/settings/active-hours")
async def update_active_hours(service_id: str, body: ActiveHours):
    _validate_service(service_id)
    settings.service(service_id).active_hours = body
    return body


@router.get("/services/{service_id}/settings/pricing")
async def get_pricing(service_id: str):
    _validate_service(service_id)
    return settings.service(service_id).pricing


@router.put("/services/{service_id}/settings/pricing")
async def update_pricing(service_id: str, body: Pricing):
    _validate_service(service_id)
    settings.service(service_id).pricing = body
    return body


# ── Announcements (/services/{service_id}/settings/announcements) ─

@router.get("/services/{service_id}/settings/announcements")
async def get_announcements(service_id: str):
    _validate_service(service_id)
    return settings.service(service_id).announcements


@router.put("/services/{service_id}/settings/announcements")
async def update_announcements(service_id: str, body: Announcements):
    _validate_service(service_id)
    settings.service(service_id).announcements = body
    return body


# ── Status (global) ───────────────────────────────────────────────

@router.get("/status")
async def system_status():
    total = 0
    services = {}
    for svc in VALID_SERVICES:
        locations = settings.service(svc).locations
        services[svc] = len(locations)
        total += len(locations)
    return {
        "total_locations": total,
        "services": services,
    }


# ── Geocoding (global) ──────────────────────────────────────────

@router.post("/geocode")
async def geocode_address(body: GeocodeRequest):
    result = get_geocode_result(body.address)
    if not result:
        raise HTTPException(status_code=404, detail="Could not geocode address")
    return {
        "latitude": result.latitude,
        "longitude": result.longitude,
        "formatted_address": result.formatted_address,
    }


# ── Service Territories (/services/{service_id}/territories) ─────

class TerritoryData(BaseModel):
    grid: list[dict]
    locations_hash: str
    computed_at: str | None
    is_partial: bool = False
    total_points: int = 0
    bounds: dict | None = None


def _compute_locations_hash(service_id: str) -> str:
    """Compute a hash of location coordinates to detect changes."""
    locations = settings.service(service_id).locations
    coords = sorted([
        f"{loc.latitude:.6f},{loc.longitude:.6f}"
        for loc in locations
        if loc.latitude and loc.longitude
    ])
    return hashlib.md5("|".join(coords).encode()).hexdigest()[:12]


@router.get("/services/{service_id}/territories")
async def get_territories(service_id: str):
    """Get cached territory data if it exists and locations haven't changed."""
    _validate_service(service_id)

    current_hash = _compute_locations_hash(service_id)
    cache_key = f"notdienststation:{service_id}:territories"

    cached = redis.get(cache_key)
    if cached:
        data = json.loads(cached.decode("utf-8"))
        if data.get("locations_hash") == current_hash:
            return data

    # No valid cache - check for partial progress
    partial_key = f"notdienststation:{service_id}:territories:partial"
    partial = redis.get(partial_key)
    if partial:
        partial_data = json.loads(partial.decode("utf-8"))
        if partial_data.get("locations_hash") == current_hash:
            return partial_data

    return {"grid": [], "locations_hash": current_hash, "computed_at": None, "is_partial": False, "total_points": 0}


@router.post("/services/{service_id}/territories")
async def save_territories(service_id: str, body: TerritoryData):
    """Save computed territory data to cache."""
    _validate_service(service_id)

    current_hash = _compute_locations_hash(service_id)
    data_to_save = body.model_dump()
    data_to_save["locations_hash"] = current_hash

    if body.is_partial:
        partial_key = f"notdienststation:{service_id}:territories:partial"
        redis.set(partial_key, json.dumps(data_to_save), ex=3600)
        return {"status": "partial_saved", "grid_size": len(body.grid)}
    else:
        cache_key = f"notdienststation:{service_id}:territories"
        redis.set(cache_key, json.dumps(data_to_save))
        partial_key = f"notdienststation:{service_id}:territories:partial"
        redis.delete(partial_key)
        return {"status": "saved", "grid_size": len(body.grid)}


# ── Calls (/calls) ───────────────────────────────────────────────

def _parse_info_yaml(raw_bytes: bytes) -> dict:
    """Parse a YAML info blob (list-of-dicts) into a single merged dict."""
    info_raw = yaml.safe_load(raw_bytes.decode("utf-8"))
    info: dict = {}
    if isinstance(info_raw, list):
        for item in info_raw:
            if isinstance(item, dict):
                info.update(item)
    elif isinstance(info_raw, dict):
        info = info_raw
    return info


@router.get("/calls")
async def list_calls():
    """List all calls from Redis using SCAN."""
    calls = []
    cursor = 0
    pattern = "notdienststation:verlauf:*:info"

    while True:
        cursor, keys = redis.scan(cursor=cursor, match=pattern, count=200)
        for key in keys:
            key_str = key.decode("utf-8") if isinstance(key, bytes) else key
            # Key format: notdienststation:verlauf:{number}:{timestamp}:info
            parts = key_str.split(":")
            if len(parts) < 5:
                continue
            number = parts[2]
            timestamp = parts[3]

            raw = redis.get(key)
            if not raw:
                continue

            try:
                info = _parse_info_yaml(raw)
            except Exception:
                continue

            raw_live = info.get("Live", False)
            is_live = raw_live is True or str(raw_live).lower() in ("ja", "true", "yes")

            # Cross-check: if the active call key has expired, the call is not live
            if is_live:
                call_number = info.get("Anrufnummer", "+" + number[2:] if number.startswith("00") else number)
                active_key = f"notdienststation:anrufe:{call_number}:gestartet_um"
                if not redis.exists(active_key):
                    is_live = False

            calls.append({
                "number": number,
                "timestamp": timestamp,
                "phone": info.get("Anrufnummer", info.get("Telefonnummer", number)),
                "start_time": info.get("Startzeit", ""),
                "intent": info.get("Anliegen", ""),
                "live": is_live,
                "location": info.get("Standort", ""),
                "provider": info.get("Anbieter", ""),
                "price": info.get("Preis", ""),
                "hangup_reason": info.get("hangup_reason", ""),
                "transferred_to": info.get("Weitergeleitet an", ""),
            })

        if cursor == 0:
            break

    # Sort by timestamp descending
    calls.sort(key=lambda c: c["timestamp"], reverse=True)
    return {"calls": calls, "total": len(calls)}


@router.get("/calls/{number}/{timestamp}")
async def get_call_detail(number: str, timestamp: str):
    """Get full detail for a single call."""
    redis_info = redis.get(
        f"notdienststation:verlauf:{number}:{timestamp}:info"
    )
    if not redis_info:
        raise HTTPException(status_code=404, detail="Call not found")

    info = _parse_info_yaml(redis_info)

    # Cross-check live status against the active call key
    raw_live = info.get("Live", False)
    if raw_live is True or str(raw_live).lower() in ("ja", "true", "yes"):
        call_number = info.get("Anrufnummer", "+" + number[2:] if number.startswith("00") else number)
        active_key = f"notdienststation:anrufe:{call_number}:gestartet_um"
        if not redis.exists(active_key):
            info["Live"] = "Nein"

    # Parse messages
    redis_messages = redis.get(
        f"notdienststation:verlauf:{number}:{timestamp}:nachrichten"
    )
    messages_raw = (
        yaml.safe_load(redis_messages.decode("utf-8")) if redis_messages else []
    )
    messages = []
    for entry in messages_raw or []:
        if not isinstance(entry, dict):
            continue
        raw_role = str(entry.get("role", "assistant"))
        role_class = raw_role.lower().replace(" ", "-")
        content = entry.get("content", "")
        model = entry.get("model")
        msg = {"role": raw_role, "role_class": role_class, "content": content}
        if model:
            msg["model"] = model
        messages.append(msg)

    # Recordings (metadata only — no base64 data)
    recordings_raw = get_available_recordings(number, timestamp) or {}
    recordings: dict[str, dict] = {}
    for rec_type, payload in recordings_raw.items():
        if not isinstance(payload, dict):
            continue
        enriched = {
            "recording_type": payload.get("recording_type", rec_type),
            "content_type": payload.get("content_type", "audio/mpeg"),
            "metadata": payload.get("metadata", {}),
            "number": number,
            "timestamp": timestamp,
        }
        recordings[rec_type] = enriched

    return {"info": info, "messages": messages, "recordings": recordings}


@router.get("/calls/{number}/{timestamp}/recording/{recording_type}")
async def get_call_recording(number: str, timestamp: str, recording_type: str):
    """Proxy audio binary through authenticated endpoint."""
    audio_bytes, content_type = get_call_recording_binary(
        number, timestamp, recording_type
    )
    if not audio_bytes:
        raise HTTPException(status_code=404, detail="Recording not found")
    return Response(content=audio_bytes, media_type=content_type)
