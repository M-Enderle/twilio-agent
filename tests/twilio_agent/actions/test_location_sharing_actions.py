"""Tests for twilio_agent.actions.location_sharing_actions."""

import os

import pytest
from pydantic import ValidationError

requires_redis = pytest.mark.skipif(
    not os.environ.get("REDIS_URL"),
    reason="REDIS_URL not set",
)


# ---- LocationData model tests (no external services needed) ----


from twilio_agent.actions.location_sharing_actions import LocationData


class TestLocationData:
    """Tests for the LocationData pydantic model."""

    def test_valid_coordinates(self):
        loc = LocationData(latitude=48.1351, longitude=11.5820)
        assert loc.latitude == 48.1351
        assert loc.longitude == 11.5820

    def test_boundary_values(self):
        loc = LocationData(latitude=90.0, longitude=180.0)
        assert loc.latitude == 90.0
        assert loc.longitude == 180.0

        loc = LocationData(latitude=-90.0, longitude=-180.0)
        assert loc.latitude == -90.0
        assert loc.longitude == -180.0

    def test_zero_coordinates(self):
        loc = LocationData(latitude=0.0, longitude=0.0)
        assert loc.latitude == 0.0
        assert loc.longitude == 0.0

    def test_latitude_out_of_range_positive(self):
        with pytest.raises(ValidationError):
            LocationData(latitude=90.1, longitude=0.0)

    def test_latitude_out_of_range_negative(self):
        with pytest.raises(ValidationError):
            LocationData(latitude=-90.1, longitude=0.0)

    def test_longitude_out_of_range_positive(self):
        with pytest.raises(ValidationError):
            LocationData(latitude=0.0, longitude=180.1)

    def test_longitude_out_of_range_negative(self):
        with pytest.raises(ValidationError):
            LocationData(latitude=0.0, longitude=-180.1)

    def test_missing_latitude(self):
        with pytest.raises(ValidationError):
            LocationData(longitude=11.0)

    def test_missing_longitude(self):
        with pytest.raises(ValidationError):
            LocationData(latitude=48.0)

    def test_string_coercion(self):
        loc = LocationData(latitude="48.5", longitude="11.2")
        assert loc.latitude == 48.5
        assert loc.longitude == 11.2

    def test_non_numeric_rejected(self):
        with pytest.raises(ValidationError):
            LocationData(latitude="abc", longitude=11.0)


# ---- Integration tests requiring Redis ----


@requires_redis
class TestGenerateLocationLink:
    """Tests for generate_location_link (requires live Redis)."""

    def test_returns_expected_keys(self):
        from twilio_agent.actions.location_sharing_actions import (
            generate_location_link,
        )

        result = generate_location_link("+4915112345678")
        assert "link_id" in result
        assert "link_url" in result
        assert "expires_at" in result

    def test_link_id_is_incrementing(self):
        from twilio_agent.actions.location_sharing_actions import (
            generate_location_link,
        )

        r1 = generate_location_link("+4915100000001")
        r2 = generate_location_link("+4915100000002")
        assert int(r2["link_id"]) > int(r1["link_id"])

    def test_link_url_contains_id(self):
        from twilio_agent.actions.location_sharing_actions import (
            generate_location_link,
        )

        result = generate_location_link("+4915100000003")
        assert result["link_id"] in result["link_url"]


@requires_redis
class TestGetLocationPage:
    """Tests for the GET /location/{link_id} endpoint (requires live Redis)."""

    def test_valid_link_returns_html(self):
        from fastapi.testclient import TestClient

        from twilio_agent.actions.location_sharing_actions import (
            generate_location_link,
            router,
        )
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        link = generate_location_link("+4915100000010")
        resp = client.get(f"/location/{link['link_id']}")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_nonexistent_link_returns_404(self):
        from fastapi.testclient import TestClient

        from twilio_agent.actions.location_sharing_actions import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        resp = client.get("/location/99999999")
        assert resp.status_code == 404


@requires_redis
class TestReceiveLocation:
    """Tests for the POST /receive-location/{link_id} endpoint."""

    def test_nonexistent_link_returns_404(self):
        from fastapi.testclient import TestClient

        from twilio_agent.actions.location_sharing_actions import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        resp = client.post(
            "/receive-location/99999999",
            json={"latitude": 48.0, "longitude": 11.0},
        )
        assert resp.status_code == 404

    def test_invalid_coordinates_rejected(self):
        from fastapi.testclient import TestClient

        from twilio_agent.actions.location_sharing_actions import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        resp = client.post(
            "/receive-location/1",
            json={"latitude": 999.0, "longitude": 11.0},
        )
        assert resp.status_code == 422
