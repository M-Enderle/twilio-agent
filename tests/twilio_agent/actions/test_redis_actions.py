"""Tests for twilio_agent.actions.redis_actions public API.

All tests that interact with Redis require a live connection and are skipped
when REDIS_URL is not configured.  Pure-logic helpers are tested without Redis.
"""

import os
import uuid

import pytest

requires_redis = pytest.mark.skipif(
    not os.environ.get("REDIS_URL"),
    reason="REDIS_URL not set",
)

# Module under test -- import after env check so module-level Redis init works
from twilio_agent.actions.redis_actions import (
    PERSISTENCE_TIME,
    _format_timed_message,
    _normalize_phone,
    _normalize_recording_type,
    add_to_caller_queue,
    agent_message,
    ai_message,
    cleanup_call,
    clear_caller_queue,
    delete_job_info,
    delete_next_caller,
    get_available_recordings,
    get_call_recording,
    get_call_recording_binary,
    get_call_timestamp,
    get_job_info,
    get_location,
    get_next_caller_in_queue,
    get_service,
    get_shared_location,
    get_transcription_text,
    get_transferred_to,
    google_message,
    init_new_call,
    redis,
    save_call_recording,
    save_job_info,
    save_location,
    set_transcription_text,
    set_transferred_to,
    twilio_message,
    user_message,
)


# -- Unique caller number per test run to avoid collisions --

def _unique_caller() -> str:
    """Return a unique fake phone number for test isolation."""
    return f"+49{uuid.uuid4().hex[:10]}"


# -- Pure helper tests (no Redis needed) --


class TestNormalizePhone:
    def test_replaces_plus(self):
        assert _normalize_phone("+491234") == "00491234"

    def test_no_plus(self):
        assert _normalize_phone("00491234") == "00491234"

    def test_empty_string(self):
        assert _normalize_phone("") == ""


class TestFormatTimedMessage:
    def test_with_duration(self):
        result = _format_timed_message("hello", 1.5)
        assert result == "hello (took 1.500s)"

    def test_without_duration(self):
        result = _format_timed_message("hello", None)
        assert result == "hello"

    def test_zero_duration(self):
        result = _format_timed_message("msg", 0.0)
        assert result == "msg (took 0.000s)"


class TestNormalizeRecordingType:
    def test_none_returns_default(self):
        assert _normalize_recording_type(None) == "initial"

    def test_empty_string_returns_default(self):
        assert _normalize_recording_type("") == "initial"

    def test_valid_initial(self):
        assert _normalize_recording_type("initial") == "initial"

    def test_valid_followup(self):
        assert _normalize_recording_type("followup") == "followup"

    def test_case_insensitive(self):
        assert _normalize_recording_type("INITIAL") == "initial"
        assert _normalize_recording_type("Followup") == "followup"

    def test_whitespace_stripped(self):
        assert _normalize_recording_type("  initial  ") == "initial"

    def test_unknown_falls_back(self):
        assert _normalize_recording_type("unknown_type") == "initial"


class TestPersistenceTime:
    def test_is_one_hour(self):
        assert PERSISTENCE_TIME == 3600


# -- Redis integration tests --


@requires_redis
class TestInitAndJobInfo:
    def test_init_new_call_and_get_service(self):
        caller = _unique_caller()
        try:
            init_new_call(caller, "test-service")
            assert get_service(caller) == "test-service"
            assert get_job_info(caller, "Live") == "Ja"
        finally:
            cleanup_call(caller)

    def test_save_and_get_job_info(self):
        caller = _unique_caller()
        try:
            init_new_call(caller, "test-service")
            save_job_info(caller, "TestKey", "TestValue")
            assert get_job_info(caller, "TestKey") == "TestValue"
        finally:
            cleanup_call(caller)

    def test_delete_job_info(self):
        caller = _unique_caller()
        try:
            init_new_call(caller, "test-service")
            save_job_info(caller, "ToDelete", "value")
            assert get_job_info(caller, "ToDelete") == "value"
            delete_job_info(caller, "ToDelete")
            assert get_job_info(caller, "ToDelete") is None
        finally:
            cleanup_call(caller)

    def test_get_job_info_missing_returns_none(self):
        caller = _unique_caller()
        assert get_job_info(caller, "nonexistent") is None


@requires_redis
class TestCallTimestamp:
    def test_returns_timestamp_after_init(self):
        caller = _unique_caller()
        try:
            init_new_call(caller, "test-service")
            ts = get_call_timestamp(caller)
            assert ts is not None
            assert "T" in ts  # format YYYYMMDDTHHMMSS
        finally:
            cleanup_call(caller)

    def test_returns_none_without_init(self):
        caller = _unique_caller()
        assert get_call_timestamp(caller) is None


@requires_redis
class TestLocation:
    def test_save_and_get_location(self):
        caller = _unique_caller()
        try:
            init_new_call(caller, "test-service")
            loc = {"latitude": 47.5, "longitude": 10.3, "formatted_address": "Test"}
            save_location(caller, loc)
            result = get_location(caller)
            assert result is not None
            assert result["latitude"] == 47.5
            assert result["formatted_address"] == "Test"
        finally:
            cleanup_call(caller)

    def test_get_location_missing_returns_none(self):
        caller = _unique_caller()
        assert get_location(caller) is None

    def test_get_shared_location_missing_returns_none(self):
        caller = _unique_caller()
        assert get_shared_location(caller) is None


@requires_redis
class TestCallerQueue:
    def test_add_and_get_next(self):
        caller = _unique_caller()
        try:
            init_new_call(caller, "test-service")
            add_to_caller_queue(caller, "Alice", "+491111")
            add_to_caller_queue(caller, "Bob", "+492222")
            nxt = get_next_caller_in_queue(caller)
            assert nxt == {"name": "Alice", "phone": "+491111"}
        finally:
            cleanup_call(caller)

    def test_delete_next_caller(self):
        caller = _unique_caller()
        try:
            init_new_call(caller, "test-service")
            add_to_caller_queue(caller, "Alice", "+491111")
            add_to_caller_queue(caller, "Bob", "+492222")
            delete_next_caller(caller)
            nxt = get_next_caller_in_queue(caller)
            assert nxt == {"name": "Bob", "phone": "+492222"}
        finally:
            cleanup_call(caller)

    def test_clear_queue(self):
        caller = _unique_caller()
        try:
            init_new_call(caller, "test-service")
            add_to_caller_queue(caller, "Alice", "+491111")
            clear_caller_queue(caller)
            assert get_next_caller_in_queue(caller) is None
        finally:
            cleanup_call(caller)

    def test_empty_queue_returns_none(self):
        caller = _unique_caller()
        assert get_next_caller_in_queue(caller) is None


@requires_redis
class TestTransferredTo:
    def test_set_and_get(self):
        caller = _unique_caller()
        try:
            init_new_call(caller, "test-service")
            set_transferred_to(caller, "+491234567890", "Max Mustermann")
            result = get_transferred_to(caller)
            assert result == ("+491234567890", "Max Mustermann")
        finally:
            cleanup_call(caller)

    def test_set_without_name(self):
        caller = _unique_caller()
        try:
            init_new_call(caller, "test-service")
            set_transferred_to(caller, "+491234567890")
            result = get_transferred_to(caller)
            assert result == ("+491234567890", "")
        finally:
            cleanup_call(caller)

    def test_get_without_set_returns_none(self):
        caller = _unique_caller()
        assert get_transferred_to(caller) is None


@requires_redis
class TestTranscription:
    def test_set_and_get(self):
        caller = _unique_caller()
        try:
            init_new_call(caller, "test-service")
            set_transcription_text(caller, "Hello world")
            assert get_transcription_text(caller) == "Hello world"
        finally:
            cleanup_call(caller)

    def test_set_none_stores_empty(self):
        caller = _unique_caller()
        try:
            init_new_call(caller, "test-service")
            set_transcription_text(caller, None)
            # get_job_info treats empty strings as None (b"" is falsy)
            assert get_transcription_text(caller) is None
        finally:
            cleanup_call(caller)


@requires_redis
class TestRecording:
    def test_save_and_retrieve(self):
        caller = _unique_caller()
        try:
            init_new_call(caller, "test-service")
            data = b"fake audio data"
            save_call_recording(caller, data, "audio/mpeg")

            ts = get_call_timestamp(caller)
            assert ts is not None
            number = _normalize_phone(caller)

            payload = get_call_recording(number, ts, "initial")
            assert payload is not None
            assert payload["content_type"] == "audio/mpeg"
            assert payload["recording_type"] == "initial"
        finally:
            cleanup_call(caller)

    def test_save_and_retrieve_binary(self):
        caller = _unique_caller()
        try:
            init_new_call(caller, "test-service")
            original = b"binary audio content"
            save_call_recording(caller, original, "audio/wav")

            ts = get_call_timestamp(caller)
            number = _normalize_phone(caller)

            audio_bytes, content_type = get_call_recording_binary(number, ts)
            assert audio_bytes == original
            assert content_type == "audio/wav"
        finally:
            cleanup_call(caller)

    def test_get_recording_missing_returns_none(self):
        assert get_call_recording("0049nonexistent", "20260101T000000") is None

    def test_get_recording_binary_missing(self):
        audio, ct = get_call_recording_binary("0049nonexistent", "20260101T000000")
        assert audio is None
        assert ct is None

    def test_anonymous_caller_skipped(self):
        save_call_recording("anonymous", b"data")
        # Should not raise

    def test_empty_bytes_skipped(self):
        save_call_recording("+491234", b"")
        # Should not raise

    def test_available_recordings(self):
        caller = _unique_caller()
        try:
            init_new_call(caller, "test-service")
            save_call_recording(caller, b"audio1", recording_type="initial")
            save_call_recording(caller, b"audio2", recording_type="followup")

            ts = get_call_timestamp(caller)
            number = _normalize_phone(caller)

            recordings = get_available_recordings(number, ts)
            assert "initial" in recordings
            assert "followup" in recordings
        finally:
            cleanup_call(caller)


@requires_redis
class TestMessages:
    """Test message logging functions don't raise."""

    def test_agent_message(self):
        caller = _unique_caller()
        try:
            init_new_call(caller, "test-service")
            agent_message(caller, "Test agent message")
        finally:
            cleanup_call(caller)

    def test_user_message(self):
        caller = _unique_caller()
        try:
            init_new_call(caller, "test-service")
            user_message(caller, "Test user message")
        finally:
            cleanup_call(caller)

    def test_ai_message_with_duration(self):
        caller = _unique_caller()
        try:
            init_new_call(caller, "test-service")
            ai_message(caller, "AI response", duration=0.5, model_source="grok")
        finally:
            cleanup_call(caller)

    def test_google_message_with_duration(self):
        caller = _unique_caller()
        try:
            init_new_call(caller, "test-service")
            google_message(caller, "Geocoded address", duration=0.3)
        finally:
            cleanup_call(caller)

    def test_twilio_message(self):
        caller = _unique_caller()
        try:
            init_new_call(caller, "test-service")
            twilio_message(caller, "Call completed")
        finally:
            cleanup_call(caller)

    def test_messages_without_init_do_not_crash(self):
        caller = _unique_caller()
        agent_message(caller, "no init")
        user_message(caller, "no init")
        ai_message(caller, "no init")
        google_message(caller, "no init")
        twilio_message(caller, "no init")


@requires_redis
class TestCleanupCall:
    def test_cleanup_removes_start_time(self):
        caller = _unique_caller()
        init_new_call(caller, "test-service")
        assert get_call_timestamp(caller) is not None
        cleanup_call(caller)
        assert get_call_timestamp(caller) is None

    def test_cleanup_nonexistent_does_not_crash(self):
        caller = _unique_caller()
        cleanup_call(caller)  # should not raise
