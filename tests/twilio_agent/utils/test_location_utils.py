"""Tests for twilio_agent.utils.location_utils module."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from twilio_agent.utils.location_utils import (
    GeocodeResult,
    _extract_plz_ort,
    _fetch_first_result,
    get_geocode_result,
    get_plz_from_coordinates,
)

# ---------------------------------------------------------------------------
# Helpers -- reusable geocode API response fragments
# ---------------------------------------------------------------------------

_MODULE = "twilio_agent.utils.location_utils"


def _make_component(long_name: str, types: list[str]) -> dict:
    """Build a single address_components entry."""
    return {"long_name": long_name, "types": types}


def _make_result(
    components: list[dict] | None = None,
    lat: float = 47.55,
    lng: float = 10.29,
    formatted_address: str = "Musterstraße 1, 87435 Kempten, Germany",
) -> dict:
    """Build a realistic Google Geocoding API result dict."""
    return {
        "address_components": components or [],
        "geometry": {"location": {"lat": lat, "lng": lng}},
        "formatted_address": formatted_address,
    }


def _ok_response(results: list[dict]) -> dict:
    """Wrap results in a full API response with status OK."""
    return {"status": "OK", "results": results}


# ===================================================================
# _extract_plz_ort
# ===================================================================


class TestExtractPlzOrt:
    """Tests for the _extract_plz_ort helper."""

    def test_extracts_plz_and_locality(self):
        result = _make_result(
            components=[
                _make_component("87435", ["postal_code"]),
                _make_component("Kempten (Allgaeu)", ["locality", "political"]),
            ]
        )
        plz, ort = _extract_plz_ort(result)
        assert plz == "87435"
        assert ort == "Kempten (Allgaeu)"

    def test_extracts_plz_and_postal_town(self):
        result = _make_result(
            components=[
                _make_component("87435", ["postal_code"]),
                _make_component("Kempten", ["postal_town"]),
            ]
        )
        plz, ort = _extract_plz_ort(result)
        assert plz == "87435"
        assert ort == "Kempten"

    def test_extracts_plz_and_admin_level_3(self):
        result = _make_result(
            components=[
                _make_component("87435", ["postal_code"]),
                _make_component("Kempten", ["administrative_area_level_3"]),
            ]
        )
        plz, ort = _extract_plz_ort(result)
        assert plz == "87435"
        assert ort == "Kempten"

    def test_missing_plz_returns_none_for_plz(self):
        result = _make_result(
            components=[
                _make_component("Kempten", ["locality"]),
            ]
        )
        plz, ort = _extract_plz_ort(result)
        assert plz is None
        assert ort == "Kempten"

    def test_missing_city_returns_none_for_ort(self):
        result = _make_result(
            components=[
                _make_component("87435", ["postal_code"]),
                _make_component("Germany", ["country"]),
            ]
        )
        plz, ort = _extract_plz_ort(result)
        assert plz == "87435"
        assert ort is None

    def test_fallback_city_type_admin_level_2(self):
        """When no primary city type is present, fall back to admin_level_2."""
        result = _make_result(
            components=[
                _make_component("87435", ["postal_code"]),
                _make_component("Oberallgaeu", ["administrative_area_level_2"]),
            ]
        )
        plz, ort = _extract_plz_ort(result)
        assert plz == "87435"
        assert ort == "Oberallgaeu"

    def test_fallback_city_type_admin_level_1(self):
        """When only admin_level_1 is present, use it as fallback."""
        result = _make_result(
            components=[
                _make_component("87435", ["postal_code"]),
                _make_component("Bayern", ["administrative_area_level_1"]),
            ]
        )
        plz, ort = _extract_plz_ort(result)
        assert plz == "87435"
        assert ort == "Bayern"

    def test_primary_city_preferred_over_fallback(self):
        """A primary city type should be chosen even when fallback types exist."""
        result = _make_result(
            components=[
                _make_component("Kempten", ["locality"]),
                _make_component("Oberallgaeu", ["administrative_area_level_2"]),
            ]
        )
        _, ort = _extract_plz_ort(result)
        assert ort == "Kempten"

    def test_empty_components_returns_none_pair(self):
        result = _make_result(components=[])
        plz, ort = _extract_plz_ort(result)
        assert plz is None
        assert ort is None

    def test_missing_components_key_returns_none_pair(self):
        result = {"geometry": {"location": {"lat": 0, "lng": 0}}}
        plz, ort = _extract_plz_ort(result)
        assert plz is None
        assert ort is None

    def test_plz_with_spaces_stripped(self):
        """Austrian PLZ can contain spaces (e.g. '6600'); verify strip logic."""
        result = _make_result(
            components=[
                _make_component("6 600", ["postal_code"]),
            ]
        )
        plz, _ = _extract_plz_ort(result)
        assert plz == "6600"

    def test_postal_code_with_empty_long_name_skipped(self):
        """A postal_code component with an empty long_name should be ignored."""
        result = _make_result(
            components=[
                _make_component("", ["postal_code"]),
            ]
        )
        plz, _ = _extract_plz_ort(result)
        assert plz is None


# ===================================================================
# _fetch_first_result
# ===================================================================


class TestFetchFirstResult:
    """Tests for the _fetch_first_result async helper."""

    @pytest.mark.asyncio
    async def test_returns_first_result_on_success(self):
        first = _make_result()
        second = _make_result(lat=48.0, lng=11.0)
        body = _ok_response([first, second])

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = body

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await _fetch_first_result({"address": "Kempten", "key": "k"})

        assert result is first

    @pytest.mark.asyncio
    async def test_returns_none_on_http_error(self):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await _fetch_first_result({"address": "bad", "key": "k"})

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_network_error(self):
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await _fetch_first_result({"address": "x", "key": "k"})

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_non_ok_status(self):
        body = {"status": "ZERO_RESULTS", "results": []}

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = body

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await _fetch_first_result({"address": "nowhere", "key": "k"})

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_empty_results(self):
        body = {"status": "OK", "results": []}

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = body

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await _fetch_first_result({"address": "empty", "key": "k"})

        assert result is None


# ===================================================================
# get_plz_from_coordinates
# ===================================================================


class TestGetPlzFromCoordinates:
    """Tests for the get_plz_from_coordinates async function."""

    @pytest.mark.asyncio
    async def test_returns_plz_for_valid_coordinates(self):
        geocode_result = _make_result(
            components=[
                _make_component("87435", ["postal_code"]),
                _make_component("Kempten", ["locality"]),
            ]
        )

        with (
            patch(f"{_MODULE}._API_KEY", "test-key"),
            patch(
                f"{_MODULE}._fetch_first_result",
                new_callable=AsyncMock,
                return_value=geocode_result,
            ) as mock_fetch,
        ):
            plz = await get_plz_from_coordinates(47.55, 10.29)

        assert plz == "87435"
        mock_fetch.assert_awaited_once()
        call_params = mock_fetch.call_args[0][0]
        assert call_params["latlng"] == "47.55,10.29"
        assert call_params["key"] == "test-key"
        assert call_params["language"] == "de"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_result(self):
        with (
            patch(f"{_MODULE}._API_KEY", "test-key"),
            patch(
                f"{_MODULE}._fetch_first_result",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            plz = await get_plz_from_coordinates(0.0, 0.0)

        assert plz is None

    @pytest.mark.asyncio
    async def test_raises_value_error_when_no_api_key(self):
        with patch(f"{_MODULE}._API_KEY", None):
            with pytest.raises(ValueError, match="MAPS_API_KEY"):
                await get_plz_from_coordinates(47.55, 10.29)

    @pytest.mark.asyncio
    async def test_raises_value_error_when_api_key_empty(self):
        with patch(f"{_MODULE}._API_KEY", ""):
            with pytest.raises(ValueError, match="MAPS_API_KEY"):
                await get_plz_from_coordinates(47.55, 10.29)

    @pytest.mark.asyncio
    async def test_returns_none_for_non_5_digit_plz(self):
        """Austrian or Swiss PLZ (4-digit) should return None."""
        geocode_result = _make_result(
            components=[
                _make_component("6600", ["postal_code"]),
                _make_component("Reutte", ["locality"]),
            ]
        )

        with (
            patch(f"{_MODULE}._API_KEY", "test-key"),
            patch(
                f"{_MODULE}._fetch_first_result",
                new_callable=AsyncMock,
                return_value=geocode_result,
            ),
        ):
            plz = await get_plz_from_coordinates(47.48, 10.72)

        assert plz is None

    @pytest.mark.asyncio
    async def test_returns_none_when_plz_missing_from_result(self):
        geocode_result = _make_result(
            components=[
                _make_component("Kempten", ["locality"]),
            ]
        )

        with (
            patch(f"{_MODULE}._API_KEY", "test-key"),
            patch(
                f"{_MODULE}._fetch_first_result",
                new_callable=AsyncMock,
                return_value=geocode_result,
            ),
        ):
            plz = await get_plz_from_coordinates(47.55, 10.29)

        assert plz is None


# ===================================================================
# get_geocode_result
# ===================================================================


class TestGetGeocodeResult:
    """Tests for the get_geocode_result async function."""

    @pytest.mark.asyncio
    async def test_returns_geocode_result_on_success(self):
        api_result = _make_result(
            components=[
                _make_component("87435", ["postal_code"]),
                _make_component("Kempten (Allgaeu)", ["locality", "political"]),
            ],
            lat=47.7267,
            lng=10.3156,
            formatted_address="Musterstraße 1, 87435 Kempten (Allgaeu), Germany",
        )

        with (
            patch(f"{_MODULE}._API_KEY", "test-key"),
            patch(
                f"{_MODULE}._fetch_first_result",
                new_callable=AsyncMock,
                return_value=api_result,
            ),
        ):
            result = await get_geocode_result("Musterstraße 1, Kempten")

        assert isinstance(result, GeocodeResult)
        assert result.latitude == 47.7267
        assert result.longitude == 10.3156
        assert result.formatted_address == "Musterstraße 1, 87435 Kempten (Allgaeu), Germany"
        assert result.plz == "87435"
        assert result.ort == "Kempten (Allgaeu)"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_result(self):
        with (
            patch(f"{_MODULE}._API_KEY", "test-key"),
            patch(
                f"{_MODULE}._fetch_first_result",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await get_geocode_result("nonexistent address 12345")

        assert result is None

    @pytest.mark.asyncio
    async def test_raises_value_error_when_no_api_key(self):
        with patch(f"{_MODULE}._API_KEY", None):
            with pytest.raises(ValueError, match="MAPS_API_KEY"):
                await get_geocode_result("Kempten")

    @pytest.mark.asyncio
    async def test_constructs_correct_google_maps_link(self):
        api_result = _make_result(
            components=[],
            lat=47.7267,
            lng=10.3156,
        )

        with (
            patch(f"{_MODULE}._API_KEY", "test-key"),
            patch(
                f"{_MODULE}._fetch_first_result",
                new_callable=AsyncMock,
                return_value=api_result,
            ),
        ):
            result = await get_geocode_result("Kempten")

        assert result.google_maps_link == "https://www.google.com/maps?q=47.7267,10.3156"

    @pytest.mark.asyncio
    async def test_passes_bounds_and_region_to_fetch(self):
        api_result = _make_result(components=[])

        with (
            patch(f"{_MODULE}._API_KEY", "test-key"),
            patch(
                f"{_MODULE}._fetch_first_result",
                new_callable=AsyncMock,
                return_value=api_result,
            ) as mock_fetch,
        ):
            await get_geocode_result("Kempten")

        call_params = mock_fetch.call_args[0][0]
        assert call_params["address"] == "Kempten"
        assert call_params["key"] == "test-key"
        assert call_params["region"] == "de"
        assert call_params["language"] == "de"
        assert "|" in call_params["bounds"]

    @pytest.mark.asyncio
    async def test_plz_and_ort_can_be_none(self):
        """When address_components lack PLZ/city, fields should be None."""
        api_result = _make_result(
            components=[
                _make_component("Germany", ["country"]),
            ],
            lat=48.0,
            lng=11.0,
        )

        with (
            patch(f"{_MODULE}._API_KEY", "test-key"),
            patch(
                f"{_MODULE}._fetch_first_result",
                new_callable=AsyncMock,
                return_value=api_result,
            ),
        ):
            result = await get_geocode_result("somewhere")

        assert result.plz is None
        assert result.ort is None

    @pytest.mark.asyncio
    async def test_formatted_address_defaults_to_empty_string(self):
        """When formatted_address is missing from the API result, default to ''."""
        api_result = {
            "address_components": [],
            "geometry": {"location": {"lat": 48.0, "lng": 11.0}},
        }

        with (
            patch(f"{_MODULE}._API_KEY", "test-key"),
            patch(
                f"{_MODULE}._fetch_first_result",
                new_callable=AsyncMock,
                return_value=api_result,
            ),
        ):
            result = await get_geocode_result("somewhere")

        assert result.formatted_address == ""
