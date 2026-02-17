"""Pricing calculation for locksmith and towing services.

Computes driving time from the caller's location to the nearest provider
using the Google Maps Routes API, then selects a price tier based on
the estimated travel duration and current time of day (day/night rates).
"""

import datetime
import json
import logging
import os

import pytz
from google.api_core.client_options import ClientOptions
from google.maps import routing_v2
from google.type import latlng_pb2

from twilio_agent.actions.redis_actions import redis
from twilio_agent.settings import settings

logger = logging.getLogger("uvicorn")

_routes_client: routing_v2.RoutesClient | None = None


def _get_routes_client() -> routing_v2.RoutesClient:
    """Return a lazily initialised Google Maps Routes client."""
    global _routes_client
    if _routes_client is None:
        api_key = settings.env.MAPS_API_KEY.get_secret_value() if settings.env.MAPS_API_KEY else None
        if not api_key:
            raise RuntimeError(
                "MAPS_API_KEY environment variable is not set; "
                "cannot initialise Google Maps Routes client."
            )
        _routes_client = routing_v2.RoutesClient(
            client_options=ClientOptions(api_key=api_key)
        )
    return _routes_client


def _get_service_pricing(
    service: str,
) -> tuple[list[tuple[int, int, int]], tuple[int, int]]:
    """Get pricing tiers and fallback prices for a service.

    Returns:
        A tuple of (tiers, fallback) where tiers is a list of
        (minutes, day_price, night_price) tuples and fallback is
        a (day_price, night_price) tuple.
    """
    pricing = settings.service(service).pricing
    tiers = [
        (t.minutes, t.dayPrice, t.nightPrice)
        for t in pricing.tiers
    ]
    fallback = (
        pricing.fallbackDayPrice,
        pricing.fallbackNightPrice,
    )
    return tiers, fallback


def _load_companies(
    intent: str, include_fallback: bool = False
) -> list[dict]:
    """Load provider locations for the given intent from Redis."""
    # Maps Location objects to dicts for compatibility with existing logic
    locations = settings.service(intent).locations

    companies = []
    for location in locations:
        companies.append(location.model_dump())

    return companies


def _compute_request(
    origin: routing_v2.Waypoint, address: str
) -> routing_v2.ComputeRoutesRequest:
    """Build a ComputeRoutesRequest from provider address to caller origin."""
    return routing_v2.ComputeRoutesRequest(
        origin=routing_v2.Waypoint(address=str(address)),
        destination=origin,
        travel_mode=routing_v2.RouteTravelMode.DRIVE,
        routing_preference=routing_v2.RoutingPreference.TRAFFIC_UNAWARE,
        language_code="de",
        units=routing_v2.Units.METRIC,
        region_code="DE",
    )


def _closest_provider(
    origin: routing_v2.Waypoint, intent: str
) -> tuple[dict | None, float, float]:
    """Find the provider with the shortest driving time to the caller.

    Returns:
        A tuple of (company_dict, distance_meters, duration_seconds).
        If no provider could be reached, returns (None, inf, inf).
    """
    closest: tuple[dict | None, float, float] = (
        None,
        float("inf"),
        float("inf"),
    )
    client = _get_routes_client()
    for company in _load_companies(intent, include_fallback=False):
        try:
            company_address = company.get(
                "address",
                company.get("adress", company.get("zipcode", "")),
            )
            response = client.compute_routes(
                request=_compute_request(origin, company_address),
                metadata=[
                    (
                        "x-goog-fieldmask",
                        "routes.distanceMeters,routes.duration",
                    )
                ],
            )
            if not response.routes:
                continue
            route = response.routes[0]
            if route.duration.seconds < closest[2]:
                closest = (
                    company,
                    route.distance_meters,
                    route.duration.seconds,
                )
        except Exception:
            logger.exception(
                "Error computing route for company %s",
                company.get("name", "unknown"),
            )
            continue
    return closest


def _origin_from_coordinates(
    longitude: float, latitude: float
) -> routing_v2.Waypoint:
    """Create a Waypoint from longitude/latitude coordinates."""
    return routing_v2.Waypoint(
        location=routing_v2.Location(
            lat_lng=latlng_pb2.LatLng(
                latitude=float(latitude),
                longitude=float(longitude),
            )
        )
    )


def _is_daytime() -> bool:
    """Check whether the current Berlin time falls within daytime hours."""
    # Use settings for day/night hours
    # Assuming locksmith service settings as default for definition of "day"
    hours = settings.service("notdienst-schluessel").active_hours
    day_start = hours.day_start
    day_end = hours.day_end

    hour = datetime.datetime.now(pytz.timezone("Europe/Berlin")).hour
    return day_start <= hour < day_end


def _price(
    duration_seconds: int | float,
    tiers: list[tuple[int, int, int]],
    fallback: tuple[int, int],
) -> tuple[int, int]:
    """Determine the price based on travel duration and time of day.

    Args:
        duration_seconds: Travel time in seconds.
        tiers: List of (minute_limit, day_price, night_price) tuples.
        fallback: (day_price, night_price) used when no tier matches.

    Returns:
        A tuple of (price, travel_minutes).
    """
    minutes = int(duration_seconds // 60)
    day = _is_daytime()
    for limit, day_price, night_price in tiers:
        if minutes < limit:
            return (day_price if day else night_price), minutes
    day_price, night_price = fallback
    return (day_price if day else night_price), minutes


def _service_price(
    origin: routing_v2.Waypoint,
    intent: str,
    tiers: list[tuple[int, int, int]],
    fallback: tuple[int, int],
) -> tuple[int, int, str, str]:
    """Calculate price and identify the closest provider.

    Args:
        origin: Caller location as a Waypoint.
        intent: Service type ("locksmith" or "towing").
        tiers: Pricing tier list.
        fallback: Fallback day/night prices.

    Returns:
        A tuple of (price, minutes, provider_name, provider_phone).

    Raises:
        ValueError: If no reachable provider was found.
    """
    provider, _, duration = _closest_provider(origin, intent)
    if provider is None:
        raise ValueError(
            f"No reachable provider found for service '{intent}'"
        )
    
    # Provider is a dict (from model_dump).
    # We need to extract name and phone.
    provider_name = provider.get("name", "")
    provider_phone = provider.get("phone", "")
    
    price, minutes = _price(duration, tiers, fallback)
    return price, max(minutes, 10), provider_name, provider_phone


def get_price_locksmith(
    longitude: float, latitude: float
) -> tuple[int, int, str, str]:
    """Get price quote for a locksmith service at the given coordinates.

    Args:
        longitude: Caller longitude.
        latitude: Caller latitude.

    Returns:
        A tuple of (price, minutes, provider_name, provider_phone).
    """
    tiers, fallback = _get_service_pricing("notdienst-schluessel")
    return _service_price(
        _origin_from_coordinates(longitude, latitude),
        "notdienst-schluessel",
        tiers,
        fallback,
    )


def get_price_towing(
    longitude: float, latitude: float
) -> tuple[int, int, str, str]:
    """Get price quote for a towing service at the given coordinates.

    Args:
        longitude: Caller longitude.
        latitude: Caller latitude.

    Returns:
        A tuple of (price, minutes, provider_name, provider_phone).
    """
    tiers, fallback = _get_service_pricing("notdienst-abschlepp")
    return _service_price(
        _origin_from_coordinates(longitude, latitude),
        "notdienst-abschlepp",
        tiers,
        fallback,
    )
