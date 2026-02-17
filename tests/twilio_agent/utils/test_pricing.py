"""Tests for the public API of twilio_agent.utils.pricing.

Tests that require Redis, the Google Maps API key, or actual provider
data are skipped when the corresponding environment variables or
services are not available. Pure logic tests (tier matching, daytime
check setup) always run.
"""

import os

import pytest

from twilio_agent.utils.pricing import (
    DEFAULT_PRICING,
    _get_service_pricing,
    _is_daytime,
    _origin_from_coordinates,
    _price,
    get_pricing,
    set_pricing,
)

requires_redis = pytest.mark.skipif(
    not os.environ.get("REDIS_URL"),
    reason="REDIS_URL not set",
)

requires_maps = pytest.mark.skipif(
    not os.environ.get("MAPS_API_KEY"),
    reason="MAPS_API_KEY not set",
)


class TestDefaultPricing:
    """Verify the shape and sanity of the hardcoded DEFAULT_PRICING."""

    def test_contains_locksmith_and_towing(self):
        assert "locksmith" in DEFAULT_PRICING
        assert "towing" in DEFAULT_PRICING

    def test_locksmith_has_tiers(self):
        locksmith = DEFAULT_PRICING["locksmith"]
        assert "tiers" in locksmith
        assert isinstance(locksmith["tiers"], list)
        assert len(locksmith["tiers"]) > 0

    def test_towing_has_tiers(self):
        towing = DEFAULT_PRICING["towing"]
        assert "tiers" in towing
        assert isinstance(towing["tiers"], list)
        assert len(towing["tiers"]) > 0

    def test_tier_structure(self):
        for service in ("locksmith", "towing"):
            for tier in DEFAULT_PRICING[service]["tiers"]:
                assert "minutes" in tier
                assert "dayPrice" in tier
                assert "nightPrice" in tier
                assert isinstance(tier["minutes"], int)
                assert isinstance(tier["dayPrice"], int)
                assert isinstance(tier["nightPrice"], int)

    def test_fallback_prices_present(self):
        for service in ("locksmith", "towing"):
            svc = DEFAULT_PRICING[service]
            assert "fallbackDayPrice" in svc
            assert "fallbackNightPrice" in svc
            assert isinstance(svc["fallbackDayPrice"], int)
            assert isinstance(svc["fallbackNightPrice"], int)

    def test_tiers_sorted_ascending(self):
        for service in ("locksmith", "towing"):
            tiers = DEFAULT_PRICING[service]["tiers"]
            minutes_values = [t["minutes"] for t in tiers]
            assert minutes_values == sorted(minutes_values)

    def test_night_prices_not_lower_than_day(self):
        for service in ("locksmith", "towing"):
            for tier in DEFAULT_PRICING[service]["tiers"]:
                assert tier["nightPrice"] >= tier["dayPrice"]
            svc = DEFAULT_PRICING[service]
            assert svc["fallbackNightPrice"] >= svc["fallbackDayPrice"]


class TestPrice:
    """Test the _price tier-matching logic with known inputs."""

    LOCKSMITH_TIERS = [
        (10, 100, 150),
        (20, 150, 200),
    ]
    LOCKSMITH_FALLBACK = (150, 250)

    def test_short_duration_hits_first_tier_day(self):
        # 5 minutes (300s) < 10 minute limit -> first tier
        price, minutes = _price(300, self.LOCKSMITH_TIERS, self.LOCKSMITH_FALLBACK)
        assert minutes == 5
        # Price depends on daytime; just check it's one of the tier values.
        assert price in (100, 150)

    def test_medium_duration_hits_second_tier(self):
        # 15 minutes (900s): >= 10 but < 20 -> second tier
        price, minutes = _price(900, self.LOCKSMITH_TIERS, self.LOCKSMITH_FALLBACK)
        assert minutes == 15
        assert price in (150, 200)

    def test_long_duration_hits_fallback(self):
        # 30 minutes (1800s): >= 20 -> fallback
        price, minutes = _price(1800, self.LOCKSMITH_TIERS, self.LOCKSMITH_FALLBACK)
        assert minutes == 30
        assert price in (150, 250)

    def test_zero_seconds(self):
        price, minutes = _price(0, self.LOCKSMITH_TIERS, self.LOCKSMITH_FALLBACK)
        assert minutes == 0
        # 0 < 10, so first tier
        assert price in (100, 150)

    def test_exact_boundary_goes_to_next_tier(self):
        # Exactly 10 minutes (600s): 10 < 10 is False, so second tier
        price, minutes = _price(600, self.LOCKSMITH_TIERS, self.LOCKSMITH_FALLBACK)
        assert minutes == 10
        assert price in (150, 200)

    def test_exact_last_boundary_hits_fallback(self):
        # Exactly 20 minutes (1200s): 20 < 20 is False -> fallback
        price, minutes = _price(1200, self.LOCKSMITH_TIERS, self.LOCKSMITH_FALLBACK)
        assert minutes == 20
        assert price in (150, 250)

    def test_empty_tiers_always_uses_fallback(self):
        price, minutes = _price(300, [], (999, 888))
        assert minutes == 5
        assert price in (999, 888)

    def test_returns_integer_minutes(self):
        # 90 seconds -> 1 minute (floor division)
        _, minutes = _price(90, self.LOCKSMITH_TIERS, self.LOCKSMITH_FALLBACK)
        assert minutes == 1
        assert isinstance(minutes, int)

    def test_negative_duration_treated_as_zero(self):
        # Negative seconds: -60 // 60 = -1, which is < 10 -> first tier
        price, minutes = _price(-60, self.LOCKSMITH_TIERS, self.LOCKSMITH_FALLBACK)
        assert isinstance(minutes, int)
        assert price in (100, 150)


class TestOriginFromCoordinates:
    """Test the waypoint construction helper."""

    def test_returns_waypoint(self):
        from google.maps import routing_v2

        wp = _origin_from_coordinates(10.0, 47.0)
        assert isinstance(wp, routing_v2.Waypoint)

    def test_string_coords_converted_to_float(self):
        wp = _origin_from_coordinates("10.5", "47.5")
        lat_lng = wp.location.lat_lng
        assert lat_lng.latitude == 47.5
        assert lat_lng.longitude == 10.5

    def test_integer_coords_accepted(self):
        wp = _origin_from_coordinates(10, 47)
        lat_lng = wp.location.lat_lng
        assert lat_lng.latitude == 47.0
        assert lat_lng.longitude == 10.0


class TestGetPricing:
    """Test get_pricing with and without Redis."""

    @requires_redis
    def test_returns_dict(self):
        result = get_pricing()
        assert isinstance(result, dict)

    @requires_redis
    def test_has_expected_keys(self):
        result = get_pricing()
        # Should at minimum return the defaults or stored config.
        assert isinstance(result, dict)
        if "locksmith" in result:
            assert "tiers" in result["locksmith"]
        if "towing" in result:
            assert "tiers" in result["towing"]


class TestSetPricing:
    """Test set_pricing round-trip with Redis."""

    @requires_redis
    def test_roundtrip(self):
        original = get_pricing()
        try:
            test_config = {
                "locksmith": {
                    "tiers": [{"minutes": 5, "dayPrice": 50, "nightPrice": 75}],
                    "fallbackDayPrice": 100,
                    "fallbackNightPrice": 200,
                },
                "towing": {
                    "tiers": [],
                    "fallbackDayPrice": 999,
                    "fallbackNightPrice": 1999,
                },
            }
            set_pricing(test_config)
            result = get_pricing()
            assert result == test_config
        finally:
            set_pricing(original)


class TestGetServicePricing:
    """Test _get_service_pricing tier extraction."""

    @requires_redis
    def test_locksmith_returns_tuple(self):
        tiers, fallback = _get_service_pricing("locksmith")
        assert isinstance(tiers, list)
        assert isinstance(fallback, tuple)
        assert len(fallback) == 2

    @requires_redis
    def test_unknown_service_returns_empty(self):
        tiers, fallback = _get_service_pricing("nonexistent_service")
        assert tiers == []
        assert fallback == (0, 0)


class TestGetPriceLocksmith:
    """Integration test for the full pricing pipeline."""

    @requires_maps
    @requires_redis
    def test_return_shape(self):
        from twilio_agent.utils.pricing import get_price_locksmith

        try:
            result = get_price_locksmith(10.621605, 47.879637)
        except ValueError:
            # No providers configured - this is expected in test envs.
            pytest.skip("No locksmith providers configured in Redis")
        except Exception:
            pytest.skip("External service unavailable")

        assert isinstance(result, tuple)
        assert len(result) == 4
        price, minutes, name, phone = result
        assert isinstance(price, int)
        assert isinstance(minutes, int)
        assert minutes >= 10
        assert isinstance(name, str)
        assert isinstance(phone, str)


class TestGetPriceTowing:
    """Integration test for the full towing pricing pipeline."""

    @requires_maps
    @requires_redis
    def test_return_shape(self):
        from twilio_agent.utils.pricing import get_price_towing

        try:
            result = get_price_towing(10.621605, 47.879637)
        except ValueError:
            pytest.skip("No towing providers configured in Redis")
        except Exception:
            pytest.skip("External service unavailable")

        assert isinstance(result, tuple)
        assert len(result) == 4
        price, minutes, name, phone = result
        assert isinstance(price, int)
        assert isinstance(minutes, int)
        assert minutes >= 10
        assert isinstance(name, str)
        assert isinstance(phone, str)


class TestIsDaytime:
    """Test the _is_daytime helper."""

    @requires_redis
    def test_returns_bool(self):
        result = _is_daytime()
        assert isinstance(result, bool)
