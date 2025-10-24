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


def _load_companies(intent: str, include_fallback: bool = False) -> list[dict]:
    with open("handwerker.yaml", "r", encoding="utf-8") as file:
        companies = yaml.safe_load(file)[intent]
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
                request=_compute_request(origin, company.get("adress", company.get("zipcode", ""))),
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
            print(f"Error computing route for {company['name']}: {e}")
            continue
    provider = closest[0]
    if provider is None:
        # Try with fallback companies
        for company in _load_companies(intent, include_fallback=True):
            try:
                response = client.compute_routes(
                    request=_compute_request(origin, company["zipcode"]),
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
                print(f"Error computing route for fallback {company['name']}: {e}")
                continue
        provider = closest[0]
        if provider is None:
            raise ValueError(f"No provider found for intent '{intent}'.")
    return closest


def _origin_from_location(location: dict):
    return routing_v2.Waypoint(
        address=f"{location['zipcode']} {location['place']}",
    )


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
    return price, max(minutes, 10), provider["name"], provider["phone"]


def get_price_locksmith(longitude, latitude):
    return _service_price(
        _origin_from_coordinates(longitude, latitude),
        "locksmith",
        LOCKSMITH_TIERS,
        LOCKSMITH_FALLBACK,
    )


def get_price_towing(longitude: str, latitude: str):
    return _service_price(
        _origin_from_coordinates(longitude, latitude),
        "towing",
        TOWING_TIERS,
        TOWING_FALLBACK,
    )


if __name__ == "__main__":
    print(get_price_locksmith(10.621605, 47.879637))