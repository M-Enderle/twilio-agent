"""Dashboard API for managing contacts and settings."""

import hashlib
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from twilio_agent.api.auth_middleware import require_auth
from twilio_agent.utils.contacts import ContactManager
from twilio_agent.utils.settings import SettingsManager
from twilio_agent.utils.location_utils import get_geocode_result
from twilio_agent.utils.pricing import get_pricing as get_pricing_config, set_pricing as set_pricing_config
from twilio_agent.actions.redis_actions import redis

logger = logging.getLogger("uvicorn")

router = APIRouter(dependencies=[Depends(require_auth)])

# Shared manager instances
cm = ContactManager()
sm = SettingsManager()


# ── Pydantic models ────────────────────────────────────────────────

class ContactCreate(BaseModel):
    name: str
    phone: str
    address: str = ""
    zipcode: str | int = ""
    fallback: bool = False
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    fallbacks_json: str = "[]"


class ContactUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    zipcode: Optional[str | int] = None
    fallback: Optional[bool] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    fallbacks_json: Optional[str] = None


class GeocodeRequest(BaseModel):
    address: str


class ReorderRequest(BaseModel):
    ids: list[str]


class VacationModeUpdate(BaseModel):
    active: bool = False
    substitute_phone: str = ""


class EmergencyContactUpdate(BaseModel):
    contact_id: str = ""
    contact_name: str = ""


class ActiveHoursUpdate(BaseModel):
    day_start: int
    day_end: int


class DirectForwardingUpdate(BaseModel):
    active: bool = False
    forward_phone: str = ""
    start_hour: float = 0.0
    end_hour: float = 6.0


class PricingTier(BaseModel):
    minutes: int
    dayPrice: int
    nightPrice: int


class ServicePricing(BaseModel):
    tiers: list[PricingTier]
    fallbackDayPrice: int
    fallbackNightPrice: int


class PricingUpdate(BaseModel):
    locksmith: ServicePricing
    towing: ServicePricing


# ── Contacts ───────────────────────────────────────────────────────

@router.get("/contacts")
async def get_contacts():
    return cm.get_all_contacts()


@router.post("/contacts/{category}", status_code=201)
async def create_contact(category: str, body: ContactCreate):
    if category not in ("locksmith", "towing"):
        raise HTTPException(status_code=400, detail="Invalid category")
    contact = cm.add_contact(category, body.model_dump())
    return contact


@router.put("/contacts/{category}/reorder")
async def reorder_contacts(category: str, body: ReorderRequest):
    if category not in ("locksmith", "towing"):
        raise HTTPException(status_code=400, detail="Invalid category")
    return cm.reorder_contacts(category, body.ids)


@router.put("/contacts/{category}/{contact_id}")
async def update_contact(category: str, contact_id: str, body: ContactUpdate):
    if category not in ("locksmith", "towing"):
        raise HTTPException(status_code=400, detail="Invalid category")
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    updated = cm.update_contact(category, contact_id, data)
    if not updated:
        raise HTTPException(status_code=404, detail="Contact not found")
    return updated


@router.delete("/contacts/{category}/{contact_id}")
async def delete_contact(category: str, contact_id: str):
    if category not in ("locksmith", "towing"):
        raise HTTPException(status_code=400, detail="Invalid category")
    deleted = cm.delete_contact(category, contact_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Contact not found")
    return {"status": "deleted"}


# ── Vacation mode ─────────────────────────────────────────────────

@router.get("/settings/vacation")
async def get_vacation_mode():
    return sm.get_vacation_mode()


@router.put("/settings/vacation")
async def update_vacation_mode(body: VacationModeUpdate):
    sm.set_vacation_mode(body.model_dump())
    return body.model_dump()


# ── Emergency contact ─────────────────────────────────────────────

@router.get("/settings/emergency-contact")
async def get_emergency_contact():
    return sm.get_emergency_contact()


@router.put("/settings/emergency-contact")
async def update_emergency_contact(body: EmergencyContactUpdate):
    sm.set_emergency_contact(body.model_dump())
    return body.model_dump()


# ── Direct forwarding ──────────────────────────────────────────────

@router.get("/settings/direct-forwarding")
async def get_direct_forwarding():
    return sm.get_direct_forwarding()


@router.put("/settings/direct-forwarding")
async def update_direct_forwarding(body: DirectForwardingUpdate):
    sm.set_direct_forwarding(body.model_dump())
    return body.model_dump()


# ── Settings ───────────────────────────────────────────────────────

@router.get("/settings/active-hours")
async def get_active_hours():
    return sm.get_active_hours()


@router.put("/settings/active-hours")
async def update_active_hours(body: ActiveHoursUpdate):
    sm.set_active_hours(body.model_dump())
    return body.model_dump()


# ── Status ─────────────────────────────────────────────────────────

@router.get("/status")
async def system_status():
    contacts = cm.get_all_contacts()
    hours = sm.get_active_hours()
    vacation = sm.get_vacation_mode()
    total = sum(len(v) for v in contacts.values())
    return {
        "total_contacts": total,
        "vacation_active": vacation.get("active", False),
        "active_hours": hours,
        "categories": {k: len(v) for k, v in contacts.items()},
    }


# ── Pricing ───────────────────────────────────────────────────────────

@router.get("/settings/pricing")
async def get_pricing():
    return get_pricing_config()


@router.put("/settings/pricing")
async def update_pricing(body: PricingUpdate):
    set_pricing_config(body.model_dump())
    return body.model_dump()


# ── Geocoding ─────────────────────────────────────────────────────────

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


# ── Service Territories (cached driving time grid) ─────────────────

class TerritoryData(BaseModel):
    grid: list[dict]
    contacts_hash: str
    computed_at: str | None
    is_partial: bool = False
    total_points: int = 0


def _compute_contacts_hash(category: str) -> str:
    """Compute a hash of contact coordinates to detect changes."""
    contacts = cm.get_all_contacts().get(category, [])
    # Only include non-fallback contacts with coordinates
    coords = sorted([
        f"{c.get('latitude', 0):.6f},{c.get('longitude', 0):.6f}"
        for c in contacts
        if not c.get("fallback") and c.get("latitude") and c.get("longitude")
    ])
    return hashlib.md5("|".join(coords).encode()).hexdigest()[:12]


@router.get("/territories/{category}")
async def get_territories(category: str):
    """Get cached territory data if it exists and contacts haven't changed."""
    if category not in ("locksmith", "towing"):
        raise HTTPException(status_code=400, detail="Invalid category")

    current_hash = _compute_contacts_hash(category)
    cache_key = f"notdienststation:territories:{category}"

    cached = redis.get(cache_key)
    if cached:
        data = json.loads(cached.decode("utf-8"))
        # Check if contacts have changed
        if data.get("contacts_hash") == current_hash:
            return data

    # No valid cache - check for partial progress
    partial_key = f"notdienststation:territories:{category}:partial"
    partial = redis.get(partial_key)
    if partial:
        partial_data = json.loads(partial.decode("utf-8"))
        if partial_data.get("contacts_hash") == current_hash:
            return partial_data

    # No cache at all
    return {"grid": [], "contacts_hash": current_hash, "computed_at": None, "is_partial": False, "total_points": 0}


@router.post("/territories/{category}")
async def save_territories(category: str, body: TerritoryData):
    """Save computed territory data to cache."""
    if category not in ("locksmith", "towing"):
        raise HTTPException(status_code=400, detail="Invalid category")

    # Compute hash from current contacts (ignore frontend hash to ensure consistency)
    current_hash = _compute_contacts_hash(category)
    data_to_save = body.model_dump()
    data_to_save["contacts_hash"] = current_hash

    if body.is_partial:
        # Save to partial cache (intermediate progress)
        partial_key = f"notdienststation:territories:{category}:partial"
        redis.set(partial_key, json.dumps(data_to_save), ex=3600)  # 1 hour expiry
        return {"status": "partial_saved", "grid_size": len(body.grid)}
    else:
        # Save to main cache (complete data)
        cache_key = f"notdienststation:territories:{category}"
        redis.set(cache_key, json.dumps(data_to_save))
        # Clear partial cache
        partial_key = f"notdienststation:territories:{category}:partial"
        redis.delete(partial_key)
        return {"status": "saved", "grid_size": len(body.grid)}
