"""Tests for twilio_agent.utils.eleven module.

Tests the ElevenLabs TTS/STT utilities: text truncation, speech
generation with caching, speech transcription via HTTP, and
recording URL construction. All external dependencies (ElevenLabs
client, cache, HTTP requests, Redis, settings) are mocked.
"""

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# _truncate_for_log
# ---------------------------------------------------------------------------

class TestTruncateForLog:
    """Tests for the _truncate_for_log helper."""

    def test_short_text_unchanged(self):
        from twilio_agent.utils.eleven import _truncate_for_log

        result = _truncate_for_log("hello", max_length=50)
        assert result == "hello"

    def test_long_text_truncated_with_ellipsis(self):
        from twilio_agent.utils.eleven import _truncate_for_log

        long_text = "a" * 100
        result = _truncate_for_log(long_text, max_length=50)
        assert result == "a" * 50 + "..."
        assert len(result) == 53

    def test_exact_boundary_not_truncated(self):
        from twilio_agent.utils.eleven import _truncate_for_log

        text = "x" * 50
        result = _truncate_for_log(text, max_length=50)
        assert result == text
        assert "..." not in result

    def test_one_over_boundary_truncated(self):
        from twilio_agent.utils.eleven import _truncate_for_log

        text = "x" * 51
        result = _truncate_for_log(text, max_length=50)
        assert result == "x" * 50 + "..."

    def test_empty_string(self):
        from twilio_agent.utils.eleven import _truncate_for_log

        assert _truncate_for_log("") == ""

    def test_custom_max_length(self):
        from twilio_agent.utils.eleven import _truncate_for_log

        result = _truncate_for_log("abcdefghij", max_length=5)
        assert result == "abcde..."


# ---------------------------------------------------------------------------
# _build_recording_url
# ---------------------------------------------------------------------------

class TestBuildRecordingUrl:
    """Tests for the _build_recording_url helper."""

    @patch("twilio_agent.utils.eleven.settings")
    def test_builds_correct_url(self, mock_settings):
        from twilio_agent.utils.eleven import _build_recording_url

        mock_settings.env.TWILIO_RECORDING_ACCOUNT = "AC_TEST_ACCOUNT"
        recording_id = "RE_abc123"

        url = _build_recording_url(recording_id)

        assert url == (
            "https://api.twilio.com/2010-04-01/Accounts/"
            "AC_TEST_ACCOUNT/Recordings/RE_abc123"
        )

    @patch("twilio_agent.utils.eleven.settings")
    def test_includes_recording_id_in_path(self, mock_settings):
        from twilio_agent.utils.eleven import _build_recording_url

        mock_settings.env.TWILIO_RECORDING_ACCOUNT = "AC_ACCT"

        url = _build_recording_url("RE_xyz789")
        assert url.endswith("/Recordings/RE_xyz789")


# ---------------------------------------------------------------------------
# generate_speech
# ---------------------------------------------------------------------------

class TestGenerateSpeech:
    """Tests for the generate_speech TTS function."""

    def test_empty_text_returns_empty_bytes(self):
        from twilio_agent.utils.eleven import generate_speech

        audio, duration = generate_speech("")
        assert audio == b""
        assert duration == 0.0

    @patch("twilio_agent.utils.eleven._elevenlabs_client", None)
    def test_no_api_key_raises_value_error(self):
        from twilio_agent.utils.eleven import generate_speech

        with pytest.raises(ValueError, match="ElevenLabs API key not configured"):
            generate_speech("Hallo Welt")

    @patch("twilio_agent.utils.eleven.cache_manager")
    @patch("twilio_agent.utils.eleven._elevenlabs_client", new_callable=MagicMock)
    def test_cache_hit_returns_cached_bytes(self, mock_client, mock_cache):
        from twilio_agent.utils.eleven import generate_speech

        cached_audio = b"cached-mp3-data"
        mock_cache.get.return_value = cached_audio

        audio, duration = generate_speech("Guten Tag")

        assert audio == cached_audio
        assert duration == 0.0
        mock_cache.get.assert_called_once_with(
            "generate_speech", {"text": "Guten Tag"}
        )
        mock_client.text_to_speech.convert.assert_not_called()

    @patch("twilio_agent.utils.eleven.settings")
    @patch("twilio_agent.utils.eleven.cache_manager")
    @patch("twilio_agent.utils.eleven._elevenlabs_client", new_callable=MagicMock)
    def test_cache_miss_calls_elevenlabs_and_caches(
        self, mock_client, mock_cache, mock_settings
    ):
        from twilio_agent.utils.eleven import generate_speech

        mock_cache.get.return_value = None
        mock_settings.env.ELEVENLABS_VOICE_ID = "test-voice-id"
        mock_settings.env.ELEVENLABS_TTS_MODEL = "eleven_v3"

        chunk1 = b"chunk-one"
        chunk2 = b"chunk-two"
        mock_client.text_to_speech.convert.return_value = iter([chunk1, chunk2])

        audio, duration = generate_speech("Hallo")

        assert audio == b"chunk-onechunk-two"
        assert duration > 0.0  # Real time elapsed, should be positive
        mock_cache.set.assert_called_once_with(
            "generate_speech",
            {"text": "Hallo"},
            b"chunk-onechunk-two",
            ".mp3",
        )

    @patch("twilio_agent.utils.eleven.settings")
    @patch("twilio_agent.utils.eleven.cache_manager")
    @patch("twilio_agent.utils.eleven._elevenlabs_client", new_callable=MagicMock)
    def test_string_chunks_encoded_to_bytes(
        self, mock_client, mock_cache, mock_settings
    ):
        from twilio_agent.utils.eleven import generate_speech

        mock_cache.get.return_value = None
        mock_settings.env.ELEVENLABS_VOICE_ID = "voice-id"
        mock_settings.env.ELEVENLABS_TTS_MODEL = "model"

        # Simulate response yielding a string chunk
        mock_client.text_to_speech.convert.return_value = iter(["string-chunk"])

        audio, _ = generate_speech("Test")

        assert audio == b"string-chunk"
        assert isinstance(audio, bytes)

    @patch("twilio_agent.utils.eleven.settings")
    @patch("twilio_agent.utils.eleven.cache_manager")
    @patch("twilio_agent.utils.eleven._elevenlabs_client", new_callable=MagicMock)
    def test_elevenlabs_exception_propagates(
        self, mock_client, mock_cache, mock_settings
    ):
        from twilio_agent.utils.eleven import generate_speech

        mock_cache.get.return_value = None
        mock_settings.env.ELEVENLABS_VOICE_ID = "voice-id"
        mock_settings.env.ELEVENLABS_TTS_MODEL = "model"
        mock_client.text_to_speech.convert.side_effect = RuntimeError("API down")

        with pytest.raises(RuntimeError, match="API down"):
            generate_speech("Test text")


# ---------------------------------------------------------------------------
# transcribe_speech
# ---------------------------------------------------------------------------

class TestTranscribeSpeech:
    """Tests for the transcribe_speech STT function."""

    @patch("twilio_agent.utils.eleven.set_transcription_text")
    @patch("twilio_agent.utils.eleven.settings")
    def test_missing_ro_sid_returns_error(self, mock_settings, mock_set_text):
        from twilio_agent.utils.eleven import transcribe_speech

        mock_settings.env.TWILIO_ACCOUNT_SID_RO = None
        mock_settings.env.TWILIO_AUTH_TOKEN_RO = MagicMock()
        mock_settings.env.TWILIO_AUTH_TOKEN_RO.get_secret_value.return_value = "token"

        result = transcribe_speech("RE_123", "+491234567890")

        assert result == ("<Error during transcription>", 0.0)
        mock_set_text.assert_not_called()

    @patch("twilio_agent.utils.eleven.set_transcription_text")
    @patch("twilio_agent.utils.eleven.settings")
    def test_missing_ro_token_returns_error(self, mock_settings, mock_set_text):
        from twilio_agent.utils.eleven import transcribe_speech

        mock_settings.env.TWILIO_ACCOUNT_SID_RO = "AC_RO"
        mock_settings.env.TWILIO_AUTH_TOKEN_RO = None

        result = transcribe_speech("RE_123", "+491234567890")

        assert result == ("<Error during transcription>", 0.0)
        mock_set_text.assert_not_called()

    @patch("twilio_agent.utils.eleven.set_transcription_text")
    @patch("twilio_agent.utils.eleven.settings")
    def test_missing_elevenlabs_key_returns_error(self, mock_settings, mock_set_text):
        from twilio_agent.utils.eleven import transcribe_speech

        mock_settings.env.TWILIO_ACCOUNT_SID_RO = "AC_RO"
        mock_settings.env.TWILIO_AUTH_TOKEN_RO = MagicMock()
        mock_settings.env.TWILIO_AUTH_TOKEN_RO.get_secret_value.return_value = "token"
        mock_settings.env.ELEVENLABS_API_KEY = None

        result = transcribe_speech("RE_123", "+491234567890")

        assert result == ("<Error during transcription>", 0.0)
        mock_set_text.assert_not_called()

    @patch("twilio_agent.utils.eleven.set_transcription_text")
    @patch("twilio_agent.utils.eleven.requests")
    @patch("twilio_agent.utils.eleven.settings")
    def test_successful_transcription(self, mock_settings, mock_requests, mock_set_text):
        from twilio_agent.utils.eleven import transcribe_speech

        mock_settings.env.TWILIO_ACCOUNT_SID_RO = "AC_RO_SID"
        ro_token = MagicMock()
        ro_token.get_secret_value.return_value = "ro_secret_token"
        mock_settings.env.TWILIO_AUTH_TOKEN_RO = ro_token

        el_key = MagicMock()
        el_key.get_secret_value.return_value = "el_api_key"
        mock_settings.env.ELEVENLABS_API_KEY = el_key

        mock_settings.env.TWILIO_RECORDING_ACCOUNT = "AC_REC_ACCT"
        mock_settings.env.ELEVENLABS_STT_MODEL = "scribe_v2"
        mock_settings.env.ELEVENLABS_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"text": "Ich brauche einen Schluessel"}
        mock_requests.post.return_value = mock_response

        result = transcribe_speech("RE_abc123", "+491234567890")

        # The function does not return a value on success (returns None),
        # but it calls set_transcription_text with the transcribed text
        mock_set_text.assert_any_call("+491234567890", None)  # Clear call
        mock_set_text.assert_any_call("+491234567890", "Ich brauche einen Schluessel")

        # Verify the HTTP POST was made with correct parameters
        mock_requests.post.assert_called_once()
        call_args = mock_requests.post.call_args
        assert call_args[0][0] == "https://api.elevenlabs.io/v1/speech-to-text"
        assert call_args[1]["headers"] == {"xi-api-key": "el_api_key"}
        assert call_args[1]["data"]["model_id"] == "scribe_v2"
        assert call_args[1]["data"]["language_code"] == "deu"
        assert call_args[1]["timeout"] == 30

    @patch("twilio_agent.utils.eleven.set_transcription_text")
    @patch("twilio_agent.utils.eleven.requests")
    @patch("twilio_agent.utils.eleven.settings")
    def test_http_error_returns_error_tuple(
        self, mock_settings, mock_requests, mock_set_text
    ):
        from twilio_agent.utils.eleven import transcribe_speech

        mock_settings.env.TWILIO_ACCOUNT_SID_RO = "AC_RO_SID"
        ro_token = MagicMock()
        ro_token.get_secret_value.return_value = "ro_secret_token"
        mock_settings.env.TWILIO_AUTH_TOKEN_RO = ro_token

        el_key = MagicMock()
        el_key.get_secret_value.return_value = "el_api_key"
        mock_settings.env.ELEVENLABS_API_KEY = el_key

        mock_settings.env.TWILIO_RECORDING_ACCOUNT = "AC_REC_ACCT"
        mock_settings.env.ELEVENLABS_STT_MODEL = "scribe_v2"
        mock_settings.env.ELEVENLABS_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_requests.post.return_value = mock_response

        result = transcribe_speech("RE_fail", "+491234567890")

        assert result == ("<Error during transcription>", 0.0)
        # set_transcription_text should have been called once to clear,
        # but NOT with the transcription result
        mock_set_text.assert_called_once_with("+491234567890", None)

    @patch("twilio_agent.utils.eleven.set_transcription_text")
    @patch("twilio_agent.utils.eleven.requests")
    @patch("twilio_agent.utils.eleven.settings")
    def test_authenticated_url_contains_credentials(
        self, mock_settings, mock_requests, mock_set_text
    ):
        from twilio_agent.utils.eleven import transcribe_speech

        mock_settings.env.TWILIO_ACCOUNT_SID_RO = "AC_MY_SID"
        ro_token = MagicMock()
        ro_token.get_secret_value.return_value = "my_auth_token"
        mock_settings.env.TWILIO_AUTH_TOKEN_RO = ro_token

        el_key = MagicMock()
        el_key.get_secret_value.return_value = "el_key"
        mock_settings.env.ELEVENLABS_API_KEY = el_key

        mock_settings.env.TWILIO_RECORDING_ACCOUNT = "AC_ACCT"
        mock_settings.env.ELEVENLABS_STT_MODEL = "scribe_v2"
        mock_settings.env.ELEVENLABS_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"text": "Test"}
        mock_requests.post.return_value = mock_response

        transcribe_speech("RE_test", "+49123")

        call_data = mock_requests.post.call_args[1]["data"]
        cloud_url = call_data["cloud_storage_url"]
        assert "AC_MY_SID:my_auth_token@" in cloud_url
        assert "api.twilio.com" in cloud_url

    @patch("twilio_agent.utils.eleven.set_transcription_text")
    @patch("twilio_agent.utils.eleven.requests")
    @patch("twilio_agent.utils.eleven.settings")
    def test_clears_transcription_before_processing(
        self, mock_settings, mock_requests, mock_set_text
    ):
        from twilio_agent.utils.eleven import transcribe_speech

        mock_settings.env.TWILIO_ACCOUNT_SID_RO = "AC_RO"
        ro_token = MagicMock()
        ro_token.get_secret_value.return_value = "token"
        mock_settings.env.TWILIO_AUTH_TOKEN_RO = ro_token

        el_key = MagicMock()
        el_key.get_secret_value.return_value = "key"
        mock_settings.env.ELEVENLABS_API_KEY = el_key

        mock_settings.env.TWILIO_RECORDING_ACCOUNT = "AC_ACCT"
        mock_settings.env.ELEVENLABS_STT_MODEL = "scribe_v2"
        mock_settings.env.ELEVENLABS_STT_URL = "https://api.elevenlabs.io/v1/stt"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"text": "result"}
        mock_requests.post.return_value = mock_response

        transcribe_speech("RE_x", "+49111")

        # First call should clear (None), second should set the text
        calls = mock_set_text.call_args_list
        assert calls[0] == (( "+49111", None),)
        assert calls[1] == (("+49111", "result"),)
