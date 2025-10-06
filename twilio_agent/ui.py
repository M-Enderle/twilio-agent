from datetime import datetime
import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from redis import Redis


router = APIRouter()


TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR, encoding="utf-8"),
    autoescape=select_autoescape(["html", "xml"]),
    enable_async=False,
)

REDIS_URL = os.getenv("REDIS_URL", "redis://:${REDIS_PASSWORD}@redis:6379")
redis = Redis.from_url(REDIS_URL)


def _scan_active_callers() -> list[dict]:
    callers: list[dict] = []
    for key in redis.scan_iter(match="callers:*:info", count=500):
        try:
            phone = key.decode("utf-8").split(":")[1]
            raw = redis.get(key)
            if not raw:
                continue
            info = json.loads(raw.decode("utf-8"))
            ts_str = info.get("timestamp")
            callers.append(
                {
                    "phone": phone,
                    "timestamp": ts_str,
                    "timestamp_sort": _parse_ts(ts_str),
                }
            )
        except Exception:
            continue
    # sort desc by time
    callers.sort(key=lambda c: c["timestamp_sort"], reverse=True)
    return callers


def _parse_ts(ts: str) -> float:
    try:
        # format like 02.10.2025 13:45:10
        return datetime.strptime(ts, "%d.%m.%Y %H:%M:%S").timestamp() if ts else 0.0
    except Exception:
        return 0.0


def _get_call_details(phone: str) -> dict:
    info_raw = redis.get(f"callers:{phone}:info")
    messages_raw = redis.get(f"callers:{phone}:messages")
    contact_raw = redis.get(f"callers:{phone}:contact")
    location_raw = redis.get(f"callers:{phone}:location")

    def _loads(raw):
        return json.loads(raw.decode("utf-8")) if raw else None

    return {
        "phone": phone,
        "info": _loads(info_raw),
        "messages": _loads(messages_raw) or [],
        "contact": _loads(contact_raw),
        "location": _loads(location_raw),
    }


@router.get("/ui", response_class=HTMLResponse)
def calls_list():
    template = jinja_env.get_template("calls_list.html")
    calls = _scan_active_callers()
    return template.render(calls=calls)


@router.get("/ui/call/{phone}", response_class=HTMLResponse)
def call_detail(phone: str):
    if not phone:
        raise HTTPException(status_code=400, detail="Missing phone")
    details = _get_call_details(phone)
    if not details.get("info") and not details.get("messages"):
        raise HTTPException(status_code=404, detail="Call not found")
    template = jinja_env.get_template("call_detail.html")
    return template.render(call=details)


