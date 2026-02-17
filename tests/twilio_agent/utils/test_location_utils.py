"""Tests for the public API of twilio_agent.utils.location_utils.

Tests that hit the Google Maps API are skipped when ``MAPS_API_KEY`` is not
set.  Pure-logic helpers are exercised unconditionally via the public
``get_geocode_result`` entry point where possible, or through the module-level
data structures.
"""

import os

import pytest

from twilio_agent.utils.location_utils import (
    GeocodeResult,
    _extract_plz_ort,
    get_geocode_result,
)

requires_maps_api = pytest.mark.skipif(
    not os.environ.get("MAPS_API_KEY"),
    reason="MAPS_API_KEY not set",
)


class TestGeocodeResult:
    """Verify the NamedTuple shape and field access."""

    def test_fields(self):
        r = GeocodeResult(
            latitude=48.0,
            longitude=11.0,
            formatted_address="Somewhere",
            google_maps_link="https://www.google.com/maps?q=48.0,11.0",
            plz="80331",
            ort="Muenchen",
        )
        assert r.latitude == 48.0
        assert r.longitude == 11.0
        assert r.formatted_address == "Somewhere"
        assert r.plz == "80331"
        assert r.ort == "Muenchen"

    def test_optional_plz_ort(self):
        r = GeocodeResult(
            latitude=0.0,
            longitude=0.0,
            formatted_address="",
            google_maps_link="",
            plz=None,
            ort=None,
        )
        assert r.plz is None
        assert r.ort is None


class TestExtractPlzOrt:
    """Test the PLZ / Ort extraction logic against synthetic API responses."""

    def test_full_components(self):
        result = {
            "address_components": [
                {"long_name": "80331", "types": ["postal_code"]},
                {"long_name": "Muenchen", "types": ["locality", "political"]},
            ]
        }
        plz, ort = _extract_plz_ort(result)
        assert plz == "80331"
        assert ort == "Muenchen"

    def test_postal_code_with_space(self):
        result = {
            "address_components": [
                {"long_name": "8033 1", "types": ["postal_code"]},
                {"long_name": "Muenchen", "types": ["locality"]},
            ]
        }
        plz, _ = _extract_plz_ort(result)
        assert plz == "80331"

    def test_no_locality_falls_back_to_admin_area(self):
        result = {
            "address_components": [
                {"long_name": "87509", "types": ["postal_code"]},
                {
                    "long_name": "Oberallgaeu",
                    "types": ["administrative_area_level_2", "political"],
                },
            ]
        }
        plz, ort = _extract_plz_ort(result)
        assert plz == "87509"
        assert ort == "Oberallgaeu"

    def test_postal_town_type(self):
        result = {
            "address_components": [
                {"long_name": "12345", "types": ["postal_code"]},
                {"long_name": "Teststadt", "types": ["postal_town"]},
            ]
        }
        _, ort = _extract_plz_ort(result)
        assert ort == "Teststadt"

    def test_admin_level_3_type(self):
        result = {
            "address_components": [
                {"long_name": "Kleindorf", "types": ["administrative_area_level_3"]},
            ]
        }
        plz, ort = _extract_plz_ort(result)
        assert plz is None
        assert ort == "Kleindorf"

    def test_empty_components(self):
        plz, ort = _extract_plz_ort({"address_components": []})
        assert plz is None
        assert ort is None

    def test_missing_key(self):
        plz, ort = _extract_plz_ort({})
        assert plz is None
        assert ort is None

    def test_component_without_long_name(self):
        result = {
            "address_components": [
                {"types": ["postal_code"]},
                {"long_name": "Stadt", "types": ["locality"]},
            ]
        }
        plz, ort = _extract_plz_ort(result)
        assert plz is None
        assert ort == "Stadt"


class TestGetGeocodeResult:
    """Tests for the main public function."""

    def test_raises_without_api_key(self, monkeypatch):
        monkeypatch.setattr(
            "twilio_agent.utils.location_utils._API_KEY", None
        )
        with pytest.raises(ValueError, match="MAPS_API_KEY"):
            get_geocode_result("some address")

    @requires_maps_api
    def test_known_address_returns_result(self):
        result = get_geocode_result("Marienplatz 1, 80331 Muenchen")
        assert result is not None
        assert isinstance(result, GeocodeResult)
        assert isinstance(result.latitude, float)
        assert isinstance(result.longitude, float)
        assert result.formatted_address != ""
        assert "google.com/maps" in result.google_maps_link

    @requires_maps_api
    def test_known_address_has_plz(self):
        result = get_geocode_result("Marienplatz 1, 80331 Muenchen")
        if result is not None:
            assert result.plz is not None
            assert result.plz.isdigit()
            assert 4 <= len(result.plz) <= 5

    @requires_maps_api
    def test_known_address_has_ort(self):
        result = get_geocode_result("Marienplatz 1, 80331 Muenchen")
        if result is not None:
            assert result.ort is not None
            assert len(result.ort) > 0

    @requires_maps_api
    def test_nonsense_address_returns_none_or_result(self):
        # Google may still geocode gibberish; we just verify no crash
        result = get_geocode_result("xyzzy123nonsense")
        assert result is None or isinstance(result, GeocodeResult)

    @requires_maps_api
    def test_plz_only_input(self):
        result = get_geocode_result("87509")
        if result is not None:
            assert isinstance(result, GeocodeResult)
            assert result.plz is not None or result.ort is not None
