"""Google Maps geocoding utilities for address resolution.

Provides forward geocoding biased to the southern-Germany / Austria service
area and extracts postal code (PLZ) and city (Ort) from the results.
"""

import logging
import os
from typing import NamedTuple, Optional

import httpx

logger = logging.getLogger(__name__)

_API_KEY = os.getenv("MAPS_API_KEY")
_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
_BOUNDS_SW = (47.41670193989541, 8.238446284078584)
_BOUNDS_NE = (48.44400690230724, 13.647079164629368)

_REQUEST_TIMEOUT = 10  # seconds

# Address component types used for city extraction, ordered by specificity.
_CITY_TYPES_PRIMARY = ("locality", "postal_town", "administrative_area_level_3")
_CITY_TYPES_FALLBACK = (
    "administrative_area_level_2",
    "administrative_area_level_1",
)


class GeocodeResult(NamedTuple):
    """Structured result of a forward geocode lookup."""

    latitude: float
    longitude: float
    formatted_address: str
    google_maps_link: str
    plz: Optional[str]
    ort: Optional[str]


async def _fetch_first_result(params: dict) -> Optional[dict]:
    """Send a geocode request to Google Maps and return the first result.

    Args:
        params: Query parameters for the Google Geocoding API.

    Returns:
        The first result dict from the API, or ``None`` on any failure.
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                _GEOCODE_URL, params=params, timeout=_REQUEST_TIMEOUT
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError:
        logger.warning("Google Geocoding API request failed", exc_info=True)
        return None

    if data.get("status") != "OK":
        logger.debug(
            "Geocoding returned non-OK status: %s", data.get("status")
        )
        return None

    results = data.get("results") or []
    return results[0] if results else None


def _extract_plz_ort(
    result: dict,
) -> tuple[Optional[str], Optional[str]]:
    """Extract postal code and city name from a geocode result.

    Walks the ``address_components`` list, trying specific locality types
    first and falling back to broader administrative areas for the city.

    Args:
        result: A single result dict from the Google Geocoding API.

    Returns:
        A ``(postal_code, city)`` tuple. Either value may be ``None``.
    """
    postal: Optional[str] = None
    city: Optional[str] = None

    for component in result.get("address_components", []):
        types = component.get("types", [])
        name = component.get("long_name")

        if not postal and "postal_code" in types and name:
            postal = name.replace(" ", "")
        if not city and any(t in types for t in _CITY_TYPES_PRIMARY):
            city = name

    if not city:
        for component in result.get("address_components", []):
            if any(
                t in component.get("types", [])
                for t in _CITY_TYPES_FALLBACK
            ):
                city = component.get("long_name")
                break

    return postal, city


async def get_plz_from_coordinates(lat: float, lon: float) -> Optional[str]:
    """Reverse-geocode coordinates and return a 4 or 5-digit postal code, or None."""
    if not _API_KEY:
        raise ValueError("MAPS_API_KEY environment variable is not set")

    result = await _fetch_first_result({
        "latlng": f"{lat},{lon}",
        "key": _API_KEY,
        "language": "de",
    })
    if not result:
        return None
    plz, _ = _extract_plz_ort(result)
    if plz and len(plz.strip()) >= 4:
        return plz
    return None


async def get_geocode_result(address: str) -> Optional[GeocodeResult]:
    """Geocode an address string using the Google Maps API.

    The lookup is biased towards the southern-Germany / Austria service
    area.

    Args:
        address: Free-form address string (may be partial).

    Returns:
        A ``GeocodeResult`` on success, or ``None`` when the address
        cannot be resolved.

    Raises:
        ValueError: If the ``MAPS_API_KEY`` environment variable is unset.
    """
    if not _API_KEY:
        raise ValueError("MAPS_API_KEY environment variable is not set")

    forward = await _fetch_first_result(
        {
            "address": address,
            "key": _API_KEY,
            "region": "de",
            "language": "de",
            "bounds": (
                f"{_BOUNDS_SW[0]},{_BOUNDS_SW[1]}"
                f"|{_BOUNDS_NE[0]},{_BOUNDS_NE[1]}"
            ),
        }
    )
    if not forward:
        return None

    location = forward["geometry"]["location"]
    latitude, longitude = location["lat"], location["lng"]
    plz, ort = _extract_plz_ort(forward)

    return GeocodeResult(
        latitude=latitude,
        longitude=longitude,
        formatted_address=forward.get("formatted_address", ""),
        google_maps_link=(
            f"https://www.google.com/maps?q={latitude},{longitude}"
        ),
        plz=plz,
        ort=ort,
    )
