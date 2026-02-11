import datetime
import json
import logging
import os

import pytz
from dotenv import load_dotenv
from google.api_core.client_options import ClientOptions
from google.maps import routing_v2
from google.type import latlng_pb2

from twilio_agent.actions.redis_actions import redis
from twilio_agent.utils.settings import SettingsManager

logger = logging.getLogger("uvicorn")

load_dotenv()
maps_api_key = os.getenv("MAPS_API_KEY")

client = routing_v2.RoutesClient(client_options=ClientOptions(api_key=maps_api_key))

PRICING_KEY = "notdienststation:config:pricing"

DEFAULT_PRICING = {
    "locksmith": {
        "tiers": [
            {"minutes": 10, "dayPrice": 100, "nightPrice": 150},
            {"minutes": 20, "dayPrice": 150, "nightPrice": 200},
        ],
        "fallbackDayPrice": 150,
        "fallbackNightPrice": 250,
    },
    "towing": {
        "tiers": [
            {"minutes": 10, "dayPrice": 150, "nightPrice": 250},
            {"minutes": 20, "dayPrice": 200, "nightPrice": 300},
        ],
        "fallbackDayPrice": 300,
        "fallbackNightPrice": 500,
    },
}


def get_pricing() -> dict:
    """Get pricing configuration from Redis."""
    raw = redis.get(PRICING_KEY)
    if not raw:
        logger.warning("Pricing config not found in Redis, using default values.")
        return DEFAULT_PRICING
    return json.loads(raw.decode("utf-8"))


def set_pricing(config: dict):
    """Save pricing configuration to Redis."""
    redis.set(PRICING_KEY, json.dumps(config, ensure_ascii=False))


def _get_service_pricing(service: str):
    """Get pricing tiers and fallback for a service."""
    config = get_pricing()
    svc = config.get(service, {})
    tiers = [(t["minutes"], t["dayPrice"], t["nightPrice"]) for t in svc.get("tiers", [])]
    fallback = (svc.get("fallbackDayPrice", 0), svc.get("fallbackNightPrice", 0))
    return tiers, fallback


def _load_companies(intent: str, include_fallback: bool = False) -> list[dict]:
    from twilio_agent.utils.contacts import ContactManager

    cm = ContactManager()
    companies = cm.get_contacts_for_category(intent)
    if not include_fallback:
        companies = [c for c in companies if not c.get("fallback")]
    return companies


def _compute_request(origin: routing_v2.Waypoint, adress: str):
    return routing_v2.ComputeRoutesRequest(
        origin=routing_v2.Waypoint(address=str(adress)),
        destination=origin,
        travel_mode=routing_v2.RouteTravelMode.DRIVE,
        routing_preference=routing_v2.RoutingPreference.TRAFFIC_UNAWARE,
        language_code="de",
        units=routing_v2.Units.METRIC,
        region_code="DE",
    )


def _closest_provider(origin: routing_v2.Waypoint, intent: str):
    closest = (None, float("inf"), float("inf"))
    for company in _load_companies(intent, include_fallback=False):
        try:
            response = client.compute_routes(
                request=_compute_request(
                    origin, company.get("address", company.get("adress", company.get("zipcode", "")))
                ),
                metadata=[
                    ("x-goog-fieldmask", "routes.distanceMeters,routes.duration")
                ],
            )
            if not response.routes:
                continue
            route = response.routes[0]
            if route.duration.seconds < closest[2]:
                closest = (company, route.distance_meters, route.duration.seconds)
        except Exception as e:
            logger.error("Error computing route for company %s: %s", company.get("name", "unknown"), e)
            continue
    return closest

def _origin_from_coordinates(longitude, latitude):
    return routing_v2.Waypoint(
        location=routing_v2.Location(
            lat_lng=latlng_pb2.LatLng(
                latitude=float(latitude),
                longitude=float(longitude),
            )
        )
    )

def _is_daytime():
    hour = datetime.datetime.now(pytz.timezone("Europe/Berlin")).hour
    config = SettingsManager().get_active_hours()
    day_start = config.get("day_start", 7)
    day_end = config.get("day_end", 20)
    return day_start <= hour < day_end


def _price(duration_seconds: int, tiers, fallback):
    minutes = duration_seconds // 60
    day = _is_daytime()
    for limit, day_price, night_price in tiers:
        if minutes < limit:
            return (day_price if day else night_price), minutes
    day_price, night_price = fallback
    return (day_price if day else night_price), minutes


def _service_price(origin: routing_v2.Waypoint, intent: str, tiers, fallback):
    provider, _, duration = _closest_provider(origin, intent)
    price, minutes = _price(duration, tiers, fallback)
    return price, max(minutes, 10), provider["name"], provider["phone"]


def get_price_locksmith(longitude, latitude):
    tiers, fallback = _get_service_pricing("locksmith")
    return _service_price(
        _origin_from_coordinates(longitude, latitude),
        "locksmith",
        tiers,
        fallback,
    )

def get_price_towing(longitude: str, latitude: str):
    tiers, fallback = _get_service_pricing("towing")
    return _service_price(
        _origin_from_coordinates(longitude, latitude),
        "towing",
        tiers,
        fallback,
    )


if __name__ == "__main__":
    print("=== Pricing Tests ===\n")

    # Test get_pricing
    print("1. get_pricing():")
    pricing = get_pricing()
    print(f"   Locksmith tiers: {pricing.get('locksmith', {}).get('tiers', [])}")
    print(f"   Towing tiers: {pricing.get('towing', {}).get('tiers', [])}")

    # Test _is_daytime
    print("\n2. _is_daytime():")
    hour = datetime.datetime.now(pytz.timezone("Europe/Berlin")).hour
    print(f"   Current hour (Berlin): {hour}")
    print(f"   Is daytime: {_is_daytime()}")

    # Test _price with different durations
    print("\n3. _price() with locksmith tiers:")
    tiers, fallback = _get_service_pricing("locksmith")
    for seconds in [300, 600, 900, 1200, 1800]:
        price, minutes = _price(seconds, tiers, fallback)
        print(f"   {seconds}s ({minutes} min) -> {price}€")

    # Test active hours config
    print("\n4. Active hours config:")
    sm = SettingsManager()
    hours = sm.get_active_hours()
    print(f"   {hours}")

    # Test full price lookup (requires Maps API)
    print("\n5. get_price_locksmith (Kempten):")
    try:
        result = get_price_locksmith(10.621605, 47.879637)
        print(f"   Price: {result[0]}€, Duration: {result[1]} min")
        print(f"   Provider: {result[2]}, Phone: {result[3]}")
    except Exception as e:
        print(f"   Error: {e}")
