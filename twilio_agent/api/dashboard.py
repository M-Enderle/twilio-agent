"""Dashboard API for managing contacts and settings."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from twilio_agent.api.auth_middleware import require_auth
from twilio_agent.utils.contacts import ContactManager

logger = logging.getLogger("uvicorn")

router = APIRouter(dependencies=[Depends(require_auth)])


# ── Pydantic models ────────────────────────────────────────────────

class ContactCreate(BaseModel):
    name: str
    phone: str
    address: str = ""
    zipcode: str | int = ""
    fallback: bool = False


class ContactUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    zipcode: Optional[str | int] = None
    fallback: Optional[bool] = None


class ReorderRequest(BaseModel):
    ids: list[str]


class VacationModeUpdate(BaseModel):
    active: bool = False
    substitute_phone: str = ""
    note: str = ""


class ActiveHoursUpdate(BaseModel):
    day_start: int
    day_end: int
    twenty_four_seven: bool = False


# ── Contacts ───────────────────────────────────────────────────────

@router.get("/contacts")
async def get_contacts():
    cm = ContactManager()
    return cm.get_all_contacts()


@router.post("/contacts/{category}", status_code=201)
async def create_contact(category: str, body: ContactCreate):
    if category not in ("locksmith", "towing"):
        raise HTTPException(status_code=400, detail="Invalid category")
    cm = ContactManager()
    contact = cm.add_contact(category, body.model_dump())
    return contact


@router.put("/contacts/{category}/reorder")
async def reorder_contacts(category: str, body: ReorderRequest):
    if category not in ("locksmith", "towing"):
        raise HTTPException(status_code=400, detail="Invalid category")
    cm = ContactManager()
    return cm.reorder_contacts(category, body.ids)


@router.put("/contacts/{category}/{contact_id}")
async def update_contact(category: str, contact_id: str, body: ContactUpdate):
    if category not in ("locksmith", "towing"):
        raise HTTPException(status_code=400, detail="Invalid category")
    cm = ContactManager()
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    updated = cm.update_contact(category, contact_id, data)
    if not updated:
        raise HTTPException(status_code=404, detail="Contact not found")
    return updated


@router.delete("/contacts/{category}/{contact_id}")
async def delete_contact(category: str, contact_id: str):
    if category not in ("locksmith", "towing"):
        raise HTTPException(status_code=400, detail="Invalid category")
    cm = ContactManager()
    deleted = cm.delete_contact(category, contact_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Contact not found")
    return {"status": "deleted"}


# ── Vacation mode ─────────────────────────────────────────────────

@router.get("/settings/vacation")
async def get_vacation_mode():
    cm = ContactManager()
    return cm.get_vacation_mode()


@router.put("/settings/vacation")
async def update_vacation_mode(body: VacationModeUpdate):
    cm = ContactManager()
    cm.set_vacation_mode(body.model_dump())
    return body.model_dump()


# ── Settings ───────────────────────────────────────────────────────

@router.get("/settings/active-hours")
async def get_active_hours():
    cm = ContactManager()
    return cm.get_active_hours()


@router.put("/settings/active-hours")
async def update_active_hours(body: ActiveHoursUpdate):
    cm = ContactManager()
    cm.set_active_hours(body.model_dump())
    return body.model_dump()


# ── Status ─────────────────────────────────────────────────────────

@router.get("/status")
async def system_status():
    cm = ContactManager()
    contacts = cm.get_all_contacts()
    hours = cm.get_active_hours()
    vacation = cm.get_vacation_mode()
    total = sum(len(v) for v in contacts.values())
    return {
        "total_contacts": total,
        "vacation_active": vacation.get("active", False),
        "active_hours": hours,
        "categories": {k: len(v) for k, v in contacts.items()},
    }
