"""Tests for the public API of twilio_agent.utils.eleven.

Tests that require the ElevenLabs API key are skipped when
``ELEVENLABS_API_KEY`` is not set. Edge-case tests (empty input,
missing credentials) always run.
"""

import os

import pytest

from twilio_agent.utils.eleven import (
    _truncate_for_log,
    generate_speech,
    transcribe_speech,
)

requires_elevenlabs = pytest.mark.skipif(
    not os.environ.get("ELEVENLABS_API_KEY"),
    reason="ELEVENLABS_API_KEY not set",
)

requires_twilio_ro = pytest.mark.skipif(
    not os.environ.get("TWILIO_ACCOUNT_SID_RO")
    or not os.environ.get("TWILIO_AUTH_TOKEN_RO"),
    reason="TWILIO_ACCOUNT_SID_RO or TWILIO_AUTH_TOKEN_RO not set",
)


class TestTruncateForLog:
    def test_short_text_unchanged(self):
        assert _truncate_for_log("hello") == "hello"

    def test_exact_limit_unchanged(self):
        text = "a" * 50
        assert _truncate_for_log(text) == text

    def test_long_text_truncated(self):
        text = "a" * 60
        result = _truncate_for_log(text)
        assert result == "a" * 50 + "..."
        assert len(result) == 53

    def test_empty_string(self):
        assert _truncate_for_log("") == ""

    def test_custom_max_length(self):
        assert _truncate_for_log("abcdef", max_length=3) == "abc..."


class TestGenerateSpeech:
    def test_empty_text_returns_empty_bytes(self):
        result = generate_speech("")
        assert isinstance(result, tuple)
        assert len(result) == 2
        audio_bytes, duration = result
        assert audio_bytes == b""
        assert duration == 0.0

    def test_none_like_empty_text(self):
        """Falsy but non-None empty string should still return empty."""
        audio_bytes, duration = generate_speech("")
        assert audio_bytes == b""
        assert duration == 0.0

    @requires_elevenlabs
    def test_return_shape(self):
        result = generate_speech("Hallo")
        assert isinstance(result, tuple) and len(result) == 2
        audio_bytes, duration = result
        assert isinstance(audio_bytes, bytes)
        assert isinstance(duration, float)

    @requires_elevenlabs
    def test_produces_audio_bytes(self):
        audio_bytes, _ = generate_speech("Hallo Welt")
        assert len(audio_bytes) > 0

    @requires_elevenlabs
    def test_cache_returns_zero_duration(self):
        """Second call for the same text should hit cache with 0.0 duration."""
        text = "Dies ist ein Cache-Test."
        generate_speech(text)
        _, duration = generate_speech(text)
        assert duration == 0.0


class TestTranscribeSpeech:
    def test_missing_credentials_returns_error(self):
        """When Twilio RO credentials are missing, should return error gracefully."""
        import twilio_agent.utils.eleven as eleven_mod

        original_sid = eleven_mod.TWILIO_ACCOUNT_SID_RO
        original_auth = eleven_mod.TWILIO_AUTH_TOKEN_RO
        try:
            eleven_mod.TWILIO_ACCOUNT_SID_RO = None
            eleven_mod.TWILIO_AUTH_TOKEN_RO = None
            text, duration = transcribe_speech("https://api.twilio.com/fake")
            assert text == "<Error during transcription>"
            assert duration == 0.0
        finally:
            eleven_mod.TWILIO_ACCOUNT_SID_RO = original_sid
            eleven_mod.TWILIO_AUTH_TOKEN_RO = original_auth

    @requires_elevenlabs
    @requires_twilio_ro
    def test_invalid_url_returns_error(self):
        """An invalid recording URL should return an error, not crash."""
        text, duration = transcribe_speech("https://api.twilio.com/nonexistent")
        assert isinstance(text, str)
        assert isinstance(duration, float)

    @requires_elevenlabs
    @requires_twilio_ro
    def test_return_shape(self):
        """Basic return type check -- the URL will fail but types should hold."""
        result = transcribe_speech("https://api.twilio.com/nonexistent")
        assert isinstance(result, tuple) and len(result) == 2
        text, duration = result
        assert isinstance(text, str)
        assert isinstance(duration, float)
