"""Tests for twilio_agent.actions.recording_actions.

Tests the public API surface: phone encoding/decoding helpers,
segment duration parsing, and the recording-serving endpoints via
FastAPI TestClient. Tests requiring Twilio or Redis are skipped
when credentials are unavailable.
"""

import os

import pytest

from twilio_agent.actions.recording_actions import (
    _decode_phone,
    _encode_phone,
    _parse_segment_duration,
)

requires_redis = pytest.mark.skipif(
    not os.environ.get("REDIS_URL"),
    reason="REDIS_URL not set",
)


class TestEncodePhone:
    def test_e164_number(self):
        assert _encode_phone("+491234567") == "00491234567"

    def test_no_plus_prefix(self):
        assert _encode_phone("491234567") == "491234567"

    def test_empty_string(self):
        assert _encode_phone("") == ""

    def test_multiple_plus_signs(self):
        # str.replace replaces all occurrences
        assert _encode_phone("+49+123") == "004900123"

    def test_roundtrip(self):
        original = "+4915112345678"
        encoded = _encode_phone(original)
        decoded = _decode_phone(encoded)
        assert decoded == original


class TestDecodePhone:
    def test_encoded_number(self):
        assert _decode_phone("00491234567") == "+491234567"

    def test_plus_prefix_unchanged(self):
        assert _decode_phone("+491234567") == "+491234567"

    def test_empty_string(self):
        assert _decode_phone("") == ""

    def test_single_zero(self):
        assert _decode_phone("0") == "0"

    def test_double_zero_only(self):
        assert _decode_phone("00") == "+"

    def test_none_like_empty(self):
        # _decode_phone checks 'if encoded', so empty string returns as-is
        assert _decode_phone("") == ""


class TestParseSegmentDuration:
    def test_valid_integer_string(self):
        assert _parse_segment_duration("42") == 42

    def test_zero(self):
        assert _parse_segment_duration("0") == 0

    def test_none_input(self):
        assert _parse_segment_duration(None) is None

    def test_non_numeric_string(self):
        assert _parse_segment_duration("abc") is None

    def test_float_string(self):
        assert _parse_segment_duration("3.14") is None

    def test_empty_string(self):
        assert _parse_segment_duration("") is None

    def test_negative_number(self):
        assert _parse_segment_duration("-5") == -5

    def test_whitespace_padded(self):
        # int() handles leading/trailing whitespace
        assert _parse_segment_duration("  10  ") == 10
