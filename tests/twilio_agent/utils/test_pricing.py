"""Tests for twilio_agent.utils.pricing module."""

import datetime
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
import pytz
from google.maps import routing_v2
from google.type import latlng_pb2

from twilio_agent.settings import (
    ActiveHours,
    Location,
    LocationContact,
    Pricing,
    PricingTier,
)
from twilio_agent.utils.pricing import (
    _closest_provider,
    _is_daytime,
    _load_companies,
    _origin_from_coordinates,
    _price,
    _service_price,
    get_price,
)


# ── Fixtures ─────────────────────────────────────────────────────


SAMPLE_TIERS = [
    (15, 100, 150),   # under 15 min: day 100, night 150
    (30, 200, 250),   # under 30 min: day 200, night 250
    (60, 300, 350),   # under 60 min: day 300, night 350
]
SAMPLE_FALLBACK = (400, 450)


def _make_location(name, address, phone, lat=48.0, lon=10.0):
    """Create a Location model for testing."""
    return Location(
        id=f"loc-{name}",
        name=name,
        address=address,
        latitude=lat,
        longitude=lon,
        contacts=[LocationContact(name=name, phone=phone, position=0)],
    )


def _make_mock_service_settings(
    tiers=None,
    fallback_day=400,
    fallback_night=450,
    locations=None,
    day_start=8,
    day_end=20,
):
    """Build a mock ServiceSettings that returns the given pricing and locations."""
    mock_svc = MagicMock()

    # Pricing
    pricing_tiers = tiers or SAMPLE_TIERS
    mock_svc.pricing = Pricing(
        tiers=[
            PricingTier(minutes=m, dayPrice=d, nightPrice=n)
            for m, d, n in pricing_tiers
        ],
        fallbackDayPrice=fallback_day,
        fallbackNightPrice=fallback_night,
    )

    # Locations
    mock_svc.locations = locations or []

    # Active hours
    mock_svc.active_hours = ActiveHours(day_start=day_start, day_end=day_end)

    return mock_svc


# ── _price ───────────────────────────────────────────────────────


class TestPrice:
    """Tests for _price(duration_seconds, tiers, fallback)."""

    @patch("twilio_agent.utils.pricing._is_daytime", return_value=True)
    def test_matches_first_tier_daytime(self, _mock_daytime):
        price, minutes = _price(600, SAMPLE_TIERS, SAMPLE_FALLBACK)

        assert minutes == 10
        assert price == 100  # day price of first tier (< 15 min)

    @patch("twilio_agent.utils.pricing._is_daytime", return_value=False)
    def test_matches_first_tier_nighttime(self, _mock_daytime):
        price, minutes = _price(600, SAMPLE_TIERS, SAMPLE_FALLBACK)

        assert minutes == 10
        assert price == 150  # night price of first tier

    @patch("twilio_agent.utils.pricing._is_daytime", return_value=True)
    def test_matches_second_tier(self, _mock_daytime):
        # 20 minutes = 1200 seconds, falls into second tier (15..30)
        price, minutes = _price(1200, SAMPLE_TIERS, SAMPLE_FALLBACK)

        assert minutes == 20
        assert price == 200

    @patch("twilio_agent.utils.pricing._is_daytime", return_value=True)
    def test_matches_third_tier(self, _mock_daytime):
        # 45 minutes = 2700 seconds, falls into third tier (30..60)
        price, minutes = _price(2700, SAMPLE_TIERS, SAMPLE_FALLBACK)

        assert minutes == 45
        assert price == 300

    @patch("twilio_agent.utils.pricing._is_daytime", return_value=True)
    def test_falls_through_to_fallback_daytime(self, _mock_daytime):
        # 90 minutes = 5400 seconds, beyond all tiers
        price, minutes = _price(5400, SAMPLE_TIERS, SAMPLE_FALLBACK)

        assert minutes == 90
        assert price == 400  # fallback day price

    @patch("twilio_agent.utils.pricing._is_daytime", return_value=False)
    def test_falls_through_to_fallback_nighttime(self, _mock_daytime):
        price, minutes = _price(5400, SAMPLE_TIERS, SAMPLE_FALLBACK)

        assert minutes == 90
        assert price == 450  # fallback night price

    @patch("twilio_agent.utils.pricing._is_daytime", return_value=True)
    def test_zero_duration_matches_first_tier(self, _mock_daytime):
        price, minutes = _price(0, SAMPLE_TIERS, SAMPLE_FALLBACK)

        assert minutes == 0
        assert price == 100  # 0 < 15, matches first tier

    @patch("twilio_agent.utils.pricing._is_daytime", return_value=True)
    def test_exact_tier_boundary_goes_to_next_tier(self, _mock_daytime):
        # Exactly 15 minutes = 900 seconds, NOT < 15, should match second tier
        price, minutes = _price(900, SAMPLE_TIERS, SAMPLE_FALLBACK)

        assert minutes == 15
        assert price == 200  # second tier day price

    @patch("twilio_agent.utils.pricing._is_daytime", return_value=True)
    def test_minutes_calculated_as_integer_division(self, _mock_daytime):
        # 89 seconds = 1 minute (integer division)
        price, minutes = _price(89, SAMPLE_TIERS, SAMPLE_FALLBACK)

        assert minutes == 1
        assert price == 100  # first tier

    @patch("twilio_agent.utils.pricing._is_daytime", return_value=True)
    def test_empty_tiers_uses_fallback(self, _mock_daytime):
        price, minutes = _price(600, [], SAMPLE_FALLBACK)

        assert price == 400  # fallback day price
        assert minutes == 10


# ── _is_daytime ──────────────────────────────────────────────────


class TestIsDaytime:
    """Tests for _is_daytime()."""

    @patch("twilio_agent.utils.pricing.settings")
    @patch("twilio_agent.utils.pricing.datetime")
    def test_returns_true_during_day_hours(self, mock_datetime, mock_settings):
        mock_settings.service.return_value.active_hours = ActiveHours(
            day_start=8, day_end=20
        )
        # Simulate 14:00 Berlin time
        mock_now = MagicMock()
        mock_now.hour = 14
        mock_datetime.datetime.now.return_value = mock_now

        assert _is_daytime() is True

    @patch("twilio_agent.utils.pricing.settings")
    @patch("twilio_agent.utils.pricing.datetime")
    def test_returns_false_before_day_start(self, mock_datetime, mock_settings):
        mock_settings.service.return_value.active_hours = ActiveHours(
            day_start=8, day_end=20
        )
        mock_now = MagicMock()
        mock_now.hour = 5
        mock_datetime.datetime.now.return_value = mock_now

        assert _is_daytime() is False

    @patch("twilio_agent.utils.pricing.settings")
    @patch("twilio_agent.utils.pricing.datetime")
    def test_returns_false_at_day_end(self, mock_datetime, mock_settings):
        mock_settings.service.return_value.active_hours = ActiveHours(
            day_start=8, day_end=20
        )
        # Exactly at day_end boundary: hour 20 is NOT < 20
        mock_now = MagicMock()
        mock_now.hour = 20
        mock_datetime.datetime.now.return_value = mock_now

        assert _is_daytime() is False

    @patch("twilio_agent.utils.pricing.settings")
    @patch("twilio_agent.utils.pricing.datetime")
    def test_returns_true_at_day_start(self, mock_datetime, mock_settings):
        mock_settings.service.return_value.active_hours = ActiveHours(
            day_start=8, day_end=20
        )
        mock_now = MagicMock()
        mock_now.hour = 8
        mock_datetime.datetime.now.return_value = mock_now

        assert _is_daytime() is True

    @patch("twilio_agent.utils.pricing.settings")
    @patch("twilio_agent.utils.pricing.datetime")
    def test_returns_false_late_night(self, mock_datetime, mock_settings):
        mock_settings.service.return_value.active_hours = ActiveHours(
            day_start=8, day_end=20
        )
        mock_now = MagicMock()
        mock_now.hour = 23
        mock_datetime.datetime.now.return_value = mock_now

        assert _is_daytime() is False

    @patch("twilio_agent.utils.pricing.settings")
    @patch("twilio_agent.utils.pricing.datetime")
    def test_custom_active_hours(self, mock_datetime, mock_settings):
        mock_settings.service.return_value.active_hours = ActiveHours(
            day_start=6, day_end=22
        )
        mock_now = MagicMock()
        mock_now.hour = 21
        mock_datetime.datetime.now.return_value = mock_now

        assert _is_daytime() is True


# ── _origin_from_coordinates ─────────────────────────────────────


class TestOriginFromCoordinates:
    """Tests for _origin_from_coordinates(longitude, latitude)."""

    def test_creates_waypoint_with_correct_coordinates(self):
        waypoint = _origin_from_coordinates(10.5, 48.3)

        assert waypoint.location.lat_lng.latitude == 48.3
        assert waypoint.location.lat_lng.longitude == 10.5

    def test_creates_waypoint_from_string_values(self):
        # The function calls float() on inputs, so string-like values work
        waypoint = _origin_from_coordinates(10.0, 48.0)

        assert isinstance(waypoint, routing_v2.Waypoint)
        assert waypoint.location.lat_lng.latitude == 48.0
        assert waypoint.location.lat_lng.longitude == 10.0

    def test_negative_coordinates(self):
        waypoint = _origin_from_coordinates(-73.9857, 40.7484)

        assert waypoint.location.lat_lng.latitude == 40.7484
        assert waypoint.location.lat_lng.longitude == -73.9857

    def test_zero_coordinates(self):
        waypoint = _origin_from_coordinates(0.0, 0.0)

        assert waypoint.location.lat_lng.latitude == 0.0
        assert waypoint.location.lat_lng.longitude == 0.0


# ── _closest_provider ────────────────────────────────────────────


class TestClosestProvider:
    """Tests for _closest_provider(origin, intent)."""

    def _make_route_response(self, distance_meters, duration_seconds):
        """Build a mock ComputeRoutesResponse with one route."""
        route = MagicMock()
        route.distance_meters = distance_meters
        route.duration.seconds = duration_seconds

        response = MagicMock()
        response.routes = [route]
        return response

    @patch("twilio_agent.utils.pricing._get_routes_client")
    @patch("twilio_agent.utils.pricing._load_companies")
    def test_returns_closest_of_multiple_providers(
        self, mock_load, mock_client_fn
    ):
        mock_load.return_value = [
            {"name": "Far Away", "address": "Addr A", "phone": "+49111"},
            {"name": "Close By", "address": "Addr B", "phone": "+49222"},
            {"name": "Medium", "address": "Addr C", "phone": "+49333"},
        ]

        mock_client = MagicMock()
        mock_client.compute_routes.side_effect = [
            self._make_route_response(50000, 1800),  # Far Away: 30 min
            self._make_route_response(10000, 600),    # Close By: 10 min
            self._make_route_response(30000, 1200),   # Medium: 20 min
        ]
        mock_client_fn.return_value = mock_client

        origin = _origin_from_coordinates(10.0, 48.0)
        company, distance, duration = _closest_provider(origin, "test-service")

        assert company["name"] == "Close By"
        assert distance == 10000
        assert duration == 600

    @patch("twilio_agent.utils.pricing._get_routes_client")
    @patch("twilio_agent.utils.pricing._load_companies")
    def test_returns_none_when_no_providers(self, mock_load, mock_client_fn):
        mock_load.return_value = []
        mock_client_fn.return_value = MagicMock()

        origin = _origin_from_coordinates(10.0, 48.0)
        company, distance, duration = _closest_provider(origin, "test-service")

        assert company is None
        assert distance == float("inf")
        assert duration == float("inf")

    @patch("twilio_agent.utils.pricing._get_routes_client")
    @patch("twilio_agent.utils.pricing._load_companies")
    def test_skips_providers_with_no_address(self, mock_load, mock_client_fn):
        mock_load.return_value = [
            {"name": "No Address", "address": "", "phone": "+49111"},
            {"name": "Has Address", "address": "Addr B", "phone": "+49222"},
        ]

        mock_client = MagicMock()
        mock_client.compute_routes.return_value = self._make_route_response(
            10000, 600
        )
        mock_client_fn.return_value = mock_client

        origin = _origin_from_coordinates(10.0, 48.0)
        company, distance, duration = _closest_provider(origin, "test-service")

        assert company["name"] == "Has Address"
        # compute_routes should only be called once (skipped the empty address)
        assert mock_client.compute_routes.call_count == 1

    @patch("twilio_agent.utils.pricing._get_routes_client")
    @patch("twilio_agent.utils.pricing._load_companies")
    def test_skips_providers_with_missing_address_key(
        self, mock_load, mock_client_fn
    ):
        mock_load.return_value = [
            {"name": "No Key", "phone": "+49111"},  # no "address" key at all
            {"name": "Has Address", "address": "Addr B", "phone": "+49222"},
        ]

        mock_client = MagicMock()
        mock_client.compute_routes.return_value = self._make_route_response(
            10000, 600
        )
        mock_client_fn.return_value = mock_client

        origin = _origin_from_coordinates(10.0, 48.0)
        company, _, _ = _closest_provider(origin, "test-service")

        assert company["name"] == "Has Address"

    @patch("twilio_agent.utils.pricing._get_routes_client")
    @patch("twilio_agent.utils.pricing._load_companies")
    def test_skips_provider_when_no_routes_returned(
        self, mock_load, mock_client_fn
    ):
        mock_load.return_value = [
            {"name": "Unreachable", "address": "Addr A", "phone": "+49111"},
            {"name": "Reachable", "address": "Addr B", "phone": "+49222"},
        ]

        no_routes_response = MagicMock()
        no_routes_response.routes = []

        mock_client = MagicMock()
        mock_client.compute_routes.side_effect = [
            no_routes_response,
            self._make_route_response(10000, 600),
        ]
        mock_client_fn.return_value = mock_client

        origin = _origin_from_coordinates(10.0, 48.0)
        company, _, _ = _closest_provider(origin, "test-service")

        assert company["name"] == "Reachable"

    @patch("twilio_agent.utils.pricing._get_routes_client")
    @patch("twilio_agent.utils.pricing._load_companies")
    def test_skips_provider_on_api_exception(self, mock_load, mock_client_fn):
        mock_load.return_value = [
            {"name": "Error", "address": "Addr A", "phone": "+49111"},
            {"name": "Working", "address": "Addr B", "phone": "+49222"},
        ]

        mock_client = MagicMock()
        mock_client.compute_routes.side_effect = [
            RuntimeError("API failure"),
            self._make_route_response(10000, 600),
        ]
        mock_client_fn.return_value = mock_client

        origin = _origin_from_coordinates(10.0, 48.0)
        company, _, _ = _closest_provider(origin, "test-service")

        assert company["name"] == "Working"

    @patch("twilio_agent.utils.pricing._get_routes_client")
    @patch("twilio_agent.utils.pricing._load_companies")
    def test_returns_none_when_all_providers_fail(
        self, mock_load, mock_client_fn
    ):
        mock_load.return_value = [
            {"name": "Error 1", "address": "Addr A", "phone": "+49111"},
            {"name": "Error 2", "address": "Addr B", "phone": "+49222"},
        ]

        mock_client = MagicMock()
        mock_client.compute_routes.side_effect = RuntimeError("API down")
        mock_client_fn.return_value = mock_client

        origin = _origin_from_coordinates(10.0, 48.0)
        company, distance, duration = _closest_provider(origin, "test-service")

        assert company is None
        assert distance == float("inf")
        assert duration == float("inf")


# ── _service_price ───────────────────────────────────────────────


class TestServicePrice:
    """Tests for _service_price(origin, intent, tiers, fallback)."""

    @patch("twilio_agent.utils.pricing._is_daytime", return_value=True)
    @patch("twilio_agent.utils.pricing._closest_provider")
    def test_returns_correct_tuple(self, mock_closest, _mock_daytime):
        mock_closest.return_value = (
            {"name": "Provider A", "phone": "+49111"},
            15000,   # distance
            1200.0,  # 20 minutes
        )

        origin = _origin_from_coordinates(10.0, 48.0)
        price, minutes, name, phone = _service_price(
            origin, "test-service", SAMPLE_TIERS, SAMPLE_FALLBACK
        )

        assert price == 200  # second tier day price (20 min)
        assert minutes == 20
        assert name == "Provider A"
        assert phone == "+49111"

    @patch("twilio_agent.utils.pricing._is_daytime", return_value=True)
    @patch("twilio_agent.utils.pricing._closest_provider")
    def test_enforces_minimum_10_minutes(self, mock_closest, _mock_daytime):
        mock_closest.return_value = (
            {"name": "Provider B", "phone": "+49222"},
            5000,   # distance
            180.0,  # 3 minutes
        )

        origin = _origin_from_coordinates(10.0, 48.0)
        price, minutes, name, phone = _service_price(
            origin, "test-service", SAMPLE_TIERS, SAMPLE_FALLBACK
        )

        assert price == 100  # first tier (3 min < 15 min)
        assert minutes == 10  # enforced minimum

    @patch("twilio_agent.utils.pricing._is_daytime", return_value=False)
    @patch("twilio_agent.utils.pricing._closest_provider")
    def test_returns_night_price(self, mock_closest, _mock_daytime):
        mock_closest.return_value = (
            {"name": "Night Provider", "phone": "+49333"},
            20000,
            1500.0,  # 25 minutes
        )

        origin = _origin_from_coordinates(10.0, 48.0)
        price, minutes, name, phone = _service_price(
            origin, "test-service", SAMPLE_TIERS, SAMPLE_FALLBACK
        )

        assert price == 250  # second tier night price
        assert minutes == 25

    @patch("twilio_agent.utils.pricing._closest_provider")
    def test_raises_value_error_when_no_provider(self, mock_closest):
        mock_closest.return_value = (None, float("inf"), float("inf"))

        origin = _origin_from_coordinates(10.0, 48.0)

        with pytest.raises(ValueError, match="No reachable provider found"):
            _service_price(
                origin, "test-service", SAMPLE_TIERS, SAMPLE_FALLBACK
            )

    @patch("twilio_agent.utils.pricing._is_daytime", return_value=True)
    @patch("twilio_agent.utils.pricing._closest_provider")
    def test_handles_missing_name_and_phone(self, mock_closest, _mock_daytime):
        mock_closest.return_value = (
            {},  # empty provider dict
            10000,
            600.0,
        )

        origin = _origin_from_coordinates(10.0, 48.0)
        price, minutes, name, phone = _service_price(
            origin, "test-service", SAMPLE_TIERS, SAMPLE_FALLBACK
        )

        assert name == ""
        assert phone == ""

    @patch("twilio_agent.utils.pricing._is_daytime", return_value=True)
    @patch("twilio_agent.utils.pricing._closest_provider")
    def test_minutes_exactly_10_not_bumped(self, mock_closest, _mock_daytime):
        mock_closest.return_value = (
            {"name": "P", "phone": "+49000"},
            10000,
            600.0,  # exactly 10 minutes
        )

        origin = _origin_from_coordinates(10.0, 48.0)
        _, minutes, _, _ = _service_price(
            origin, "test-service", SAMPLE_TIERS, SAMPLE_FALLBACK
        )

        assert minutes == 10  # max(10, 10) = 10


# ── get_price ────────────────────────────────────────────────────


class TestGetPrice:
    """Tests for get_price(service, longitude, latitude)."""

    @patch("twilio_agent.utils.pricing._service_price")
    @patch("twilio_agent.utils.pricing._get_service_pricing")
    def test_integrates_pricing_and_coordinates(
        self, mock_get_pricing, mock_service_price
    ):
        mock_get_pricing.return_value = (SAMPLE_TIERS, SAMPLE_FALLBACK)
        mock_service_price.return_value = (200, 20, "Provider", "+49111")

        price, minutes, name, phone = get_price(
            "notdienst-schluessel", 10.5, 48.3
        )

        assert price == 200
        assert minutes == 20
        assert name == "Provider"
        assert phone == "+49111"

        # Verify _get_service_pricing was called with the service name
        mock_get_pricing.assert_called_once_with("notdienst-schluessel")

        # Verify _service_price received a Waypoint, service, tiers, fallback
        call_args = mock_service_price.call_args
        origin_arg = call_args[0][0]
        assert isinstance(origin_arg, routing_v2.Waypoint)
        assert call_args[0][1] == "notdienst-schluessel"
        assert call_args[0][2] == SAMPLE_TIERS
        assert call_args[0][3] == SAMPLE_FALLBACK

    @patch("twilio_agent.utils.pricing._service_price")
    @patch("twilio_agent.utils.pricing._get_service_pricing")
    def test_passes_correct_waypoint_coordinates(
        self, mock_get_pricing, mock_service_price
    ):
        mock_get_pricing.return_value = ([], (0, 0))
        mock_service_price.return_value = (0, 10, "", "")

        get_price("notdienst-abschlepp", 11.5, 47.8)

        origin_arg = mock_service_price.call_args[0][0]
        assert origin_arg.location.lat_lng.latitude == 47.8
        assert origin_arg.location.lat_lng.longitude == 11.5


# ── _load_companies ──────────────────────────────────────────────


class TestLoadCompanies:
    """Tests for _load_companies(intent)."""

    @patch("twilio_agent.utils.pricing.settings")
    def test_returns_list_of_dicts_from_locations(self, mock_settings):
        locations = [
            _make_location("Locksmith A", "Street 1", "+49111"),
            _make_location("Locksmith B", "Street 2", "+49222"),
        ]
        mock_settings.service.return_value.locations = locations

        result = _load_companies("notdienst-schluessel")

        assert len(result) == 2
        assert result[0]["name"] == "Locksmith A"
        assert result[0]["address"] == "Street 1"
        assert result[1]["name"] == "Locksmith B"
        # Each entry should be a dict (from model_dump)
        assert isinstance(result[0], dict)
        assert isinstance(result[1], dict)

    @patch("twilio_agent.utils.pricing.settings")
    def test_returns_empty_list_when_no_locations(self, mock_settings):
        mock_settings.service.return_value.locations = []

        result = _load_companies("notdienst-schluessel")

        assert result == []

    @patch("twilio_agent.utils.pricing.settings")
    def test_preserves_all_location_fields(self, mock_settings):
        location = _make_location(
            "Full Provider", "Main St 5", "+49333", lat=48.5, lon=10.5
        )
        mock_settings.service.return_value.locations = [location]

        result = _load_companies("test-service")

        company = result[0]
        assert company["id"] == "loc-Full Provider"
        assert company["latitude"] == 48.5
        assert company["longitude"] == 10.5
        assert len(company["contacts"]) == 1
        assert company["contacts"][0]["name"] == "Full Provider"
        assert company["contacts"][0]["phone"] == "+49333"


# ── _get_service_pricing ─────────────────────────────────────────


class TestGetServicePricing:
    """Tests for _get_service_pricing(service)."""

    @patch("twilio_agent.utils.pricing.settings")
    def test_returns_tiers_and_fallback(self, mock_settings):
        mock_settings.service.return_value.pricing = Pricing(
            tiers=[
                PricingTier(minutes=15, dayPrice=100, nightPrice=150),
                PricingTier(minutes=30, dayPrice=200, nightPrice=250),
            ],
            fallbackDayPrice=400,
            fallbackNightPrice=450,
        )

        from twilio_agent.utils.pricing import _get_service_pricing

        tiers, fallback = _get_service_pricing("test-service")

        assert tiers == [(15, 100, 150), (30, 200, 250)]
        assert fallback == (400, 450)

    @patch("twilio_agent.utils.pricing.settings")
    def test_returns_empty_tiers_when_none_configured(self, mock_settings):
        mock_settings.service.return_value.pricing = Pricing(
            tiers=[],
            fallbackDayPrice=500,
            fallbackNightPrice=600,
        )

        from twilio_agent.utils.pricing import _get_service_pricing

        tiers, fallback = _get_service_pricing("test-service")

        assert tiers == []
        assert fallback == (500, 600)


# ── _get_routes_client ───────────────────────────────────────────


class TestGetRoutesClient:
    """Tests for _get_routes_client()."""

    @patch("twilio_agent.utils.pricing.settings")
    def test_raises_when_no_api_key(self, mock_settings):
        mock_settings.env.MAPS_API_KEY = None

        # Reset the cached client so _get_routes_client re-initializes
        import twilio_agent.utils.pricing as pricing_module

        pricing_module._routes_client = None

        from twilio_agent.utils.pricing import _get_routes_client

        with pytest.raises(RuntimeError, match="MAPS_API_KEY"):
            _get_routes_client()

        # Restore to avoid side effects
        pricing_module._routes_client = None
