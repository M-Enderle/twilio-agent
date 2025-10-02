import datetime
import os

import pytz
import yaml
from dotenv import load_dotenv
from google.api_core.client_options import ClientOptions
from google.maps import routing_v2
from google.type import latlng_pb2

load_dotenv()
maps_api_key = os.getenv("MAPS_API_KEY")

client = routing_v2.RoutesClient(client_options=ClientOptions(api_key=maps_api_key))

LOCKSMITH_TIERS = [(10, 100, 150), (20, 150, 200)]
LOCKSMITH_FALLBACK = (150, 250)
TOWING_TIERS = [(10, 150, 250), (20, 200, 300)]
TOWING_FALLBACK = (300, 500)


def _load_companies(intent: str):
    with open("handwerker.yaml", "r", encoding="utf-8") as file:
        return [c for c in yaml.safe_load(file)[intent] if not c.get("fallback")]


def _compute_request(origin: routing_v2.Waypoint, zipcode: str):
    return routing_v2.ComputeRoutesRequest(
        origin=origin,
        destination=routing_v2.Waypoint(address=str(zipcode)),
        travel_mode=routing_v2.RouteTravelMode.DRIVE,
        routing_preference=routing_v2.RoutingPreference.TRAFFIC_AWARE_OPTIMAL,
        language_code="de",
        units=routing_v2.Units.METRIC,
        region_code="DE",
    )


def _closest_provider(origin: routing_v2.Waypoint, intent: str):
    closest = (None, float("inf"), float("inf"))
    for company in _load_companies(intent):
        try:
            response = client.compute_routes(
                request=_compute_request(origin, company["zipcode"]),
                metadata=[("x-goog-fieldmask", "routes.distanceMeters,routes.duration")],
            )
            if not response.routes:
                continue
            route = response.routes[0]
            if route.duration.seconds < closest[2]:
                closest = (company, route.distance_meters, route.duration.seconds)
        except Exception:
            continue
    provider = closest[0]
    if provider is None:
        raise ValueError(f"No provider found for intent '{intent}'.")
    return closest


def _origin_from_location(location: dict):
    return routing_v2.Waypoint(
        address=f"{location['zipcode']} {location['place']}",
    )


def _origin_from_coordinates(longitude: str, latitude: str):
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
    return 7 <= hour < 20


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
    return price, minutes, provider["name"], provider["phone"]


def get_price_locksmith(location: dict):
    return _service_price(
        _origin_from_location(location),
        "locksmith",
        LOCKSMITH_TIERS,
        LOCKSMITH_FALLBACK,
    )


def get_price_towing(location: dict):
    return _service_price(
        _origin_from_location(location),
        "towing",
        TOWING_TIERS,
        TOWING_FALLBACK,
    )


def get_price_towing_coordinates(longitude: str, latitude: str):
    return _service_price(
        _origin_from_coordinates(longitude, latitude),
        "towing",
        TOWING_TIERS,
        TOWING_FALLBACK,
    )


if __name__ == "__main__":
    print(get_price_towing_coordinates("13.388860", "52.517037"))
    print(get_price_locksmith({"zipcode": "10115", "place": "Berlin"}))
    print(get_price_towing({"zipcode": "40210", "place": "Düsseldorf"}))