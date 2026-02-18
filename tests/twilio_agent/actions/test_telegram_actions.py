"""Tests for twilio_agent.actions.telegram_actions module."""

import os
import re

import pytest
import pytest_asyncio  # noqa: F401 (ensures plugin is loaded)

from twilio_agent.actions.telegram_actions import (
    _get_berlin_time,
    _is_localhost_url,
    _BERLIN_TZ,
    _SERVICE_EMOJI,
    send_message,
    send_simple_notification,
    send_telegram_notification,
)

requires_telegram = pytest.mark.skipif(
    not os.environ.get("TELEGRAM_BOT_TOKEN"),
    reason="TELEGRAM_BOT_TOKEN not set",
)

requires_redis = pytest.mark.skipif(
    not os.environ.get("REDIS_URL"),
    reason="REDIS_URL not set",
)


class TestIsLocalhostUrl:
    """Tests for the _is_localhost_url helper."""

    def test_localhost_in_url(self):
        assert _is_localhost_url("http://localhost:8000/path") is True

    def test_127_0_0_1_in_url(self):
        assert _is_localhost_url("http://127.0.0.1:8000/path") is True

    def test_production_url(self):
        assert _is_localhost_url("https://example.com/path") is False

    def test_localhost_as_substring(self):
        # "localhost" appearing as a substring still matches
        assert _is_localhost_url("http://my-localhost-server/path") is True

    def test_empty_string(self):
        assert _is_localhost_url("") is False

    def test_https_localhost(self):
        assert _is_localhost_url("https://localhost/secure") is True


class TestGetBerlinTime:
    """Tests for the _get_berlin_time helper."""

    def test_returns_string(self):
        result = _get_berlin_time()
        assert isinstance(result, str)

    def test_format_is_hh_mm_ss(self):
        result = _get_berlin_time()
        assert re.match(r"^\d{2}:\d{2}:\d{2}$", result), (
            f"Expected HH:MM:SS format, got '{result}'"
        )

    def test_hours_in_valid_range(self):
        result = _get_berlin_time()
        hours = int(result.split(":")[0])
        assert 0 <= hours <= 23


class TestModuleConstants:
    """Tests for module-level constants."""

    def test_berlin_tz_is_set(self):
        assert str(_BERLIN_TZ) == "Europe/Berlin"

    def test_service_emoji_keys(self):
        expected_keys = {
            "schluessel-allgaeu",
            "notdienst-schluessel",
            "notdienst-abschlepp",
        }
        assert set(_SERVICE_EMOJI.keys()) == expected_keys

    def test_service_emoji_values_are_nonempty(self):
        for service_id, emoji in _SERVICE_EMOJI.items():
            assert len(emoji) > 0, (
                f"Emoji for {service_id} should not be empty"
            )


class TestSendMessage:
    """Tests for the send_message async function."""

    @pytest.mark.asyncio
    async def test_no_bot_token_returns_none(self, caplog):
        """When no bot token is available, function logs error and returns."""
        # With no token configured, the function should exit early
        result = await send_message(
            "https://example.com/track",
            "+491234567890",
            chat_id="123",
            bot_token=None,
        )
        assert result is None

    @requires_telegram
    @pytest.mark.asyncio
    async def test_send_with_valid_token(self):
        """Smoke test with real credentials -- skipped if not configured."""
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        if not chat_id:
            pytest.skip("TELEGRAM_CHAT_ID not set")

        result = await send_message(
            "https://example.com/test",
            "+491234567890",
            chat_id=chat_id,
            bot_token=bot_token,
        )
        assert result is None


class TestSendSimpleNotification:
    """Tests for the send_simple_notification async function."""

    @pytest.mark.asyncio
    async def test_no_service_id_returns_early(self, caplog):
        """Without service_id, no bot token is resolved, logs error."""
        result = await send_simple_notification(
            "+491234567890", service_id=None
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_filtered_number_not_sent(self, caplog):
        """The hardcoded test number 17657888 should be filtered out."""
        # Even if token resolution fails, the filter is applied later.
        # This primarily verifies the function doesn't crash.
        result = await send_simple_notification(
            "17657888", service_id=None
        )
        assert result is None


class TestSendTelegramNotification:
    """Tests for the send_telegram_notification async function."""

    @requires_redis
    @pytest.mark.asyncio
    async def test_returns_string(self):
        """Basic smoke test -- requires Redis to resolve timestamp."""
        result = await send_telegram_notification(
            "+491234567890", service_id=None
        )
        assert isinstance(result, str)

    @requires_redis
    @pytest.mark.asyncio
    async def test_localhost_url_still_returns_url(self):
        """Even with localhost, the function should return the URL."""
        # This test depends on DASHBOARD_URL / SERVER_URL being localhost
        # in the test environment. If not, the result will still be a
        # non-empty string.
        result = await send_telegram_notification("+491234567890")
        assert isinstance(result, str)
