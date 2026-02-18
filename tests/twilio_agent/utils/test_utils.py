"""Tests for twilio_agent.utils.utils module.

Tests the public API surface: service identification from phone numbers,
direct transfer time-window logic, and Twilio request data extraction.
All external dependencies (settings, datetime, _get_caller) are mocked.
"""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz


MODULE_PATH = "twilio_agent.utils.utils"


# ── Helpers ───────────────────────────────────────────────────────


def _make_mock_settings(phone_map: dict[str, str]) -> MagicMock:
    """Build a mock settings object that maps service_id -> phone_number.

    ``phone_map`` is e.g. {"schluessel-allgaeu": "+49 123 456"}.
    Services not present in the map get an empty phone_number.
    """
    mock_settings = MagicMock()

    def service_side_effect(service_id):
        svc = MagicMock()
        phone = phone_map.get(service_id, "")
        svc.phone_number.phone_number = phone
        return svc

    mock_settings.service.side_effect = service_side_effect
    return mock_settings


def _make_forwarding_settings(
    active: bool = True,
    forward_phone: str = "+49 999 000",
    start_hour: int = 0,
    end_hour: int = 6,
) -> MagicMock:
    """Build a mock service settings object with direct_forwarding fields."""
    svc = MagicMock()
    svc.direct_forwarding.active = active
    svc.direct_forwarding.forward_phone = forward_phone
    svc.direct_forwarding.start_hour = start_hour
    svc.direct_forwarding.end_hour = end_hour
    return svc


def _berlin_datetime(hour: int, minute: int = 0) -> datetime.datetime:
    """Return a timezone-aware datetime in Europe/Berlin at the given hour."""
    tz = pytz.timezone("Europe/Berlin")
    return tz.localize(datetime.datetime(2026, 2, 17, hour, minute, 0))


# ── which_service ─────────────────────────────────────────────────


class TestWhichService:
    """Tests for which_service()."""

    def test_matches_known_phone_number(self):
        phone_map = {
            "schluessel-allgaeu": "+4912345",
            "notdienst-schluessel": "+4967890",
            "notdienst-abschlepp": "+4911111",
        }
        mock_settings = _make_mock_settings(phone_map)

        with patch(f"{MODULE_PATH}.settings", mock_settings):
            from twilio_agent.utils.utils import which_service

            result = which_service("+4967890")

        assert result == "notdienst-schluessel"

    def test_strips_spaces_from_input(self):
        phone_map = {
            "schluessel-allgaeu": "+4912345",
            "notdienst-schluessel": "+4967890",
            "notdienst-abschlepp": "+4911111",
        }
        mock_settings = _make_mock_settings(phone_map)

        with patch(f"{MODULE_PATH}.settings", mock_settings):
            from twilio_agent.utils.utils import which_service

            result = which_service("+49 678 90")

        assert result == "notdienst-schluessel"

    def test_strips_spaces_from_stored_number(self):
        phone_map = {
            "schluessel-allgaeu": "+49 123 45",
            "notdienst-schluessel": "+4967890",
            "notdienst-abschlepp": "+4911111",
        }
        mock_settings = _make_mock_settings(phone_map)

        with patch(f"{MODULE_PATH}.settings", mock_settings):
            from twilio_agent.utils.utils import which_service

            result = which_service("+4912345")

        assert result == "schluessel-allgaeu"

    def test_returns_none_for_unknown_number(self):
        phone_map = {
            "schluessel-allgaeu": "+4912345",
            "notdienst-schluessel": "+4967890",
            "notdienst-abschlepp": "+4911111",
        }
        mock_settings = _make_mock_settings(phone_map)

        with patch(f"{MODULE_PATH}.settings", mock_settings):
            from twilio_agent.utils.utils import which_service

            result = which_service("+4999999")

        assert result is None

    def test_returns_first_match_when_duplicates(self):
        """When two services share a number, the first in VALID_SERVICES wins."""
        phone_map = {
            "schluessel-allgaeu": "+4912345",
            "notdienst-schluessel": "+4912345",
            "notdienst-abschlepp": "+4911111",
        }
        mock_settings = _make_mock_settings(phone_map)

        with patch(f"{MODULE_PATH}.settings", mock_settings):
            from twilio_agent.utils.utils import which_service

            result = which_service("+4912345")

        assert result == "schluessel-allgaeu"

    def test_empty_input_returns_none(self):
        phone_map = {
            "schluessel-allgaeu": "+4912345",
            "notdienst-schluessel": "+4967890",
            "notdienst-abschlepp": "+4911111",
        }
        mock_settings = _make_mock_settings(phone_map)

        with patch(f"{MODULE_PATH}.settings", mock_settings):
            from twilio_agent.utils.utils import which_service

            result = which_service("")

        assert result is None


# ── direct_transfer ───────────────────────────────────────────────


class TestDirectTransfer:
    """Tests for direct_transfer()."""

    def test_returns_true_when_active_and_within_time_range(self):
        svc = _make_forwarding_settings(
            active=True, forward_phone="+49999", start_hour=0, end_hour=6
        )
        mock_settings = MagicMock()
        mock_settings.service.return_value = svc

        fixed_time = _berlin_datetime(hour=3)

        with (
            patch(f"{MODULE_PATH}.settings", mock_settings),
            patch(f"{MODULE_PATH}.datetime") as mock_dt,
        ):
            mock_dt.datetime.now.return_value = fixed_time
            from twilio_agent.utils.utils import direct_transfer

            result = direct_transfer("schluessel-allgaeu")

        assert result is True

    def test_returns_false_when_not_active(self):
        svc = _make_forwarding_settings(
            active=False, forward_phone="+49999", start_hour=0, end_hour=6
        )
        mock_settings = MagicMock()
        mock_settings.service.return_value = svc

        fixed_time = _berlin_datetime(hour=3)

        with (
            patch(f"{MODULE_PATH}.settings", mock_settings),
            patch(f"{MODULE_PATH}.datetime") as mock_dt,
        ):
            mock_dt.datetime.now.return_value = fixed_time
            from twilio_agent.utils.utils import direct_transfer

            result = direct_transfer("schluessel-allgaeu")

        assert result is False

    def test_returns_false_when_outside_time_range(self):
        svc = _make_forwarding_settings(
            active=True, forward_phone="+49999", start_hour=0, end_hour=6
        )
        mock_settings = MagicMock()
        mock_settings.service.return_value = svc

        fixed_time = _berlin_datetime(hour=10)

        with (
            patch(f"{MODULE_PATH}.settings", mock_settings),
            patch(f"{MODULE_PATH}.datetime") as mock_dt,
        ):
            mock_dt.datetime.now.return_value = fixed_time
            from twilio_agent.utils.utils import direct_transfer

            result = direct_transfer("schluessel-allgaeu")

        assert result is False

    def test_returns_false_when_no_forward_phone(self):
        svc = _make_forwarding_settings(
            active=True, forward_phone="", start_hour=0, end_hour=6
        )
        mock_settings = MagicMock()
        mock_settings.service.return_value = svc

        fixed_time = _berlin_datetime(hour=3)

        with (
            patch(f"{MODULE_PATH}.settings", mock_settings),
            patch(f"{MODULE_PATH}.datetime") as mock_dt,
        ):
            mock_dt.datetime.now.return_value = fixed_time
            from twilio_agent.utils.utils import direct_transfer

            result = direct_transfer("schluessel-allgaeu")

        assert result is False

    def test_returns_true_at_start_hour_boundary(self):
        svc = _make_forwarding_settings(
            active=True, forward_phone="+49999", start_hour=8, end_hour=20
        )
        mock_settings = MagicMock()
        mock_settings.service.return_value = svc

        fixed_time = _berlin_datetime(hour=8)

        with (
            patch(f"{MODULE_PATH}.settings", mock_settings),
            patch(f"{MODULE_PATH}.datetime") as mock_dt,
        ):
            mock_dt.datetime.now.return_value = fixed_time
            from twilio_agent.utils.utils import direct_transfer

            result = direct_transfer("schluessel-allgaeu")

        assert result is True

    def test_returns_false_at_end_hour_boundary(self):
        """end_hour is exclusive (< not <=), so hour == end_hour is outside."""
        svc = _make_forwarding_settings(
            active=True, forward_phone="+49999", start_hour=8, end_hour=20
        )
        mock_settings = MagicMock()
        mock_settings.service.return_value = svc

        fixed_time = _berlin_datetime(hour=20)

        with (
            patch(f"{MODULE_PATH}.settings", mock_settings),
            patch(f"{MODULE_PATH}.datetime") as mock_dt,
        ):
            mock_dt.datetime.now.return_value = fixed_time
            from twilio_agent.utils.utils import direct_transfer

            result = direct_transfer("schluessel-allgaeu")

        assert result is False

    def test_returns_false_one_hour_before_start(self):
        svc = _make_forwarding_settings(
            active=True, forward_phone="+49999", start_hour=8, end_hour=20
        )
        mock_settings = MagicMock()
        mock_settings.service.return_value = svc

        fixed_time = _berlin_datetime(hour=7)

        with (
            patch(f"{MODULE_PATH}.settings", mock_settings),
            patch(f"{MODULE_PATH}.datetime") as mock_dt,
        ):
            mock_dt.datetime.now.return_value = fixed_time
            from twilio_agent.utils.utils import direct_transfer

            result = direct_transfer("schluessel-allgaeu")

        assert result is False


# ── get_caller_number / get_called_number / call_info ─────────────


class TestGetCallerNumber:
    """Tests for get_caller_number()."""

    @pytest.mark.asyncio
    async def test_returns_caller_from_request(self):
        mock_request = MagicMock()
        expected_caller = "+4915112345678"

        with patch(f"{MODULE_PATH}._get_caller", new_callable=AsyncMock) as mock_get_caller:
            mock_get_caller.return_value = expected_caller
            from twilio_agent.utils.utils import get_caller_number

            result = await get_caller_number(mock_request)

        assert result == expected_caller
        mock_get_caller.assert_awaited_once_with(mock_request)

    @pytest.mark.asyncio
    async def test_passes_request_to_caller(self):
        mock_request = MagicMock()

        with patch(f"{MODULE_PATH}._get_caller", new_callable=AsyncMock) as mock_get_caller:
            mock_get_caller.return_value = "+49000"
            from twilio_agent.utils.utils import get_caller_number

            await get_caller_number(mock_request)

        mock_get_caller.assert_awaited_once_with(mock_request)


class TestGetCalledNumber:
    """Tests for get_called_number()."""

    @pytest.mark.asyncio
    async def test_returns_called_number_from_request(self):
        mock_request = MagicMock()
        expected_called = "+4930123456"

        with patch(f"{MODULE_PATH}._get_caller", new_callable=AsyncMock) as mock_get_caller:
            mock_get_caller.return_value = expected_called
            from twilio_agent.utils.utils import get_called_number

            result = await get_called_number(mock_request)

        assert result == expected_called
        mock_get_caller.assert_awaited_once_with(mock_request, called=True)

    @pytest.mark.asyncio
    async def test_passes_called_true_to_caller(self):
        mock_request = MagicMock()

        with patch(f"{MODULE_PATH}._get_caller", new_callable=AsyncMock) as mock_get_caller:
            mock_get_caller.return_value = "+49000"
            from twilio_agent.utils.utils import get_called_number

            await get_called_number(mock_request)

        mock_get_caller.assert_awaited_once_with(mock_request, called=True)


class TestCallInfo:
    """Tests for call_info()."""

    @pytest.mark.asyncio
    async def test_returns_caller_called_and_form_data(self):
        mock_request = MagicMock()
        mock_form = {"Caller": "+491111", "Called": "+492222", "Digits": "1"}
        mock_request.form = AsyncMock(return_value=mock_form)

        with patch(f"{MODULE_PATH}._get_caller", new_callable=AsyncMock) as mock_get_caller:
            mock_get_caller.side_effect = ["+491111", "+492222"]
            from twilio_agent.utils.utils import call_info

            caller_number, called_number, form_data = await call_info(mock_request)

        assert caller_number == "+491111"
        assert called_number == "+492222"
        assert form_data == mock_form

    @pytest.mark.asyncio
    async def test_calls_caller_twice(self):
        """call_info calls _get_caller() once without called, once with called=True."""
        mock_request = MagicMock()
        mock_request.form = AsyncMock(return_value={})

        with patch(f"{MODULE_PATH}._get_caller", new_callable=AsyncMock) as mock_get_caller:
            mock_get_caller.side_effect = ["+491111", "+492222"]
            from twilio_agent.utils.utils import call_info

            await call_info(mock_request)

        assert mock_get_caller.await_count == 2
        mock_get_caller.assert_any_await(mock_request)
        mock_get_caller.assert_any_await(mock_request, called=True)

    @pytest.mark.asyncio
    async def test_form_data_is_awaited(self):
        mock_request = MagicMock()
        mock_request.form = AsyncMock(return_value={"SpeechResult": "Ja"})

        with patch(f"{MODULE_PATH}._get_caller", new_callable=AsyncMock) as mock_get_caller:
            mock_get_caller.return_value = "+49000"
            from twilio_agent.utils.utils import call_info

            _, _, form_data = await call_info(mock_request)

        mock_request.form.assert_awaited_once()
        assert form_data["SpeechResult"] == "Ja"
