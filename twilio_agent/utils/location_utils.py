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
BOUNDS_SW = (47.41670193989541, 8.238446284078584)
BOUNDS_NE = (48.44400690230724, 13.647079164629368)


def _fetch_first_result(params: dict) -> Optional[dict]:
    try:
        response = requests.get(GEOCODE_URL, params=params)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        return None

    if data.get("status") != "OK":
        return None

    results = data.get("results") or []
    if not results:
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
        {
            "address": address,
            "key": API_KEY,
            "region": "de",
            "language": "de",
            "bounds": f"{BOUNDS_SW[0]},{BOUNDS_SW[1]}|{BOUNDS_NE[0]},{BOUNDS_NE[1]}",
        }
    )
    if not forward:
        return None

    location = forward["geometry"]["location"]
    latitude, longitude = location["lat"], location["lng"]
    result = forward
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
    print("=== Location Utils Tests ===\n")

    # Test API key
    print("1. API Key:")
    print(f"   Set: {bool(API_KEY)}")

    # Test geocoding with address
    print("\n2. get_geocode_result('Kempten'):")
    try:
        result = get_geocode_result("Kempten")
        if result:
            print(f"   Latitude: {result.latitude}")
            print(f"   Longitude: {result.longitude}")
            print(f"   Address: {result.formatted_address}")
            print(f"   PLZ: {result.plz}")
            print(f"   Ort: {result.ort}")
            print(f"   Maps: {result.google_maps_link}")
        else:
            print("   No result found")
    except Exception as e:
        print(f"   Error: {e}")

    # Test geocoding with PLZ
    print("\n3. get_geocode_result('87435'):")
    try:
        result = get_geocode_result("87435")
        if result:
            print(f"   Latitude: {result.latitude}")
            print(f"   Longitude: {result.longitude}")
            print(f"   Address: {result.formatted_address}")
            print(f"   PLZ: {result.plz}")
            print(f"   Ort: {result.ort}")
        else:
            print("   No result found")
    except Exception as e:
        print(f"   Error: {e}")

    # Test bounds
    print("\n4. Search bounds (Bayern):")
    print(f"   SW: {BOUNDS_SW}")
    print(f"   NE: {BOUNDS_NE}")
