import json
import os
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple, Optional

import requests
from dotenv import load_dotenv


class GeocodeResult(NamedTuple):
    latitude: float
    longitude: float
    formatted_address: str
    google_maps_link: str
    plz: Optional[str]
    ort: Optional[str]


load_dotenv()
API_KEY = os.getenv("MAPS_API_KEY")
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
ZIPCODE_FILES = ("zipcodes.de.json", "zipcodes.at.json")


def _fetch_first_result(params: dict) -> Optional[dict]:
    try:
        response = requests.get(GEOCODE_URL, params=params)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        print(f"Request failed: {exc}")
        return None

    if data.get("status") != "OK":
        print(
            f"API error: {data.get('status')} - {data.get('error_message', 'No error message')}"
        )
        return None

    results = data.get("results") or []
    if not results:
        print("No results found")
        return None

    return results[0]


def _extract_plz_ort(result: dict) -> tuple[Optional[str], Optional[str]]:
    postal = city = None

    for component in result.get("address_components", []):
        types = component.get("types", [])
        name = component.get("long_name")

        if not postal and "postal_code" in types and name:
            postal = name.replace(" ", "")
        if not city and any(
            t in types
            for t in ("locality", "postal_town", "administrative_area_level_3")
        ):
            city = name

    if not city:
        for component in result.get("address_components", []):
            if any(
                t in component.get("types", [])
                for t in ("administrative_area_level_2", "administrative_area_level_1")
            ):
                city = component.get("long_name")
                break

    return postal, city


def get_geocode_result(address: str) -> Optional[GeocodeResult]:
    if not API_KEY:
        raise ValueError("MAPS_API_KEY environment variable is not set")

    forward = _fetch_first_result(
        {"address": address, "key": API_KEY, "region": "de", "language": "de"}
    )
    if not forward:
        return None

    location = forward["geometry"]["location"]
    latitude, longitude = location["lat"], location["lng"]

    reverse = _fetch_first_result(
        {"latlng": f"{latitude},{longitude}", "key": API_KEY, "language": "de"}
    )
    result = reverse or forward
    plz, ort = _extract_plz_ort(result)

    return GeocodeResult(
        latitude=latitude,
        longitude=longitude,
        formatted_address=result.get("formatted_address", ""),
        google_maps_link=f"https://www.google.com/maps?q={latitude},{longitude}",
        plz=plz,
        ort=ort,
    )

if __name__ == "__main__":
    test_addresses = [
        "Brandenburger Tor, Berlin",
        "Marienplatz, München",
        "Stephansdom, Wien",
        "Invalid Address 12345",
    ]
    for addr in test_addresses:
        result = get_geocode_result(addr)
        print(f"Address: {addr}\nResult: {result}\n")
