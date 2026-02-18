"""Tests for twilio_agent.utils.cache.CacheManager.

Uses real filesystem via pytest's ``tmp_path`` fixture. The module-level
``_root_cache_folder`` is monkeypatched so that all CacheManager instances
write into a temporary directory instead of the production cache root.
"""

import hashlib
import json

import pytest

import twilio_agent.utils.cache as cache_module
from twilio_agent.utils.cache import CacheManager


@pytest.fixture(autouse=True)
def _patch_cache_root(tmp_path, monkeypatch):
    """Redirect all CacheManager instances to write under tmp_path."""
    monkeypatch.setattr(cache_module, "_root_cache_folder", tmp_path)


# ---------------------------------------------------------------------------
# Cache key generation
# ---------------------------------------------------------------------------


class TestGetCacheKey:
    def test_simple_ascii_string(self, tmp_path):
        cm = CacheManager("test")
        key = cm.get_cache_key({"text": "hello world"})
        assert key == "hello_world"

    def test_sorted_key_order(self, tmp_path):
        cm = CacheManager("test")
        key_ab = cm.get_cache_key({"a": "alpha", "b": "beta"})
        key_ba = cm.get_cache_key({"b": "beta", "a": "alpha"})
        assert key_ab == key_ba
        assert key_ab == "alpha_beta"

    def test_unicode_accents_stripped(self, tmp_path):
        cm = CacheManager("test")
        key = cm.get_cache_key({"text": "Muenchen Strasse"})
        assert "u" in key
        # German umlauts decomposed and accent marks removed
        key_umlaut = cm.get_cache_key({"text": "\u00fc\u00f6\u00e4"})
        assert key_umlaut == "uoa"

    def test_special_characters_removed(self, tmp_path):
        cm = CacheManager("test")
        key = cm.get_cache_key({"text": "hello! @world# $2024"})
        assert key == "hello_world_2024"

    def test_multiple_spaces_collapsed(self, tmp_path):
        cm = CacheManager("test")
        key = cm.get_cache_key({"text": "hello   world"})
        assert key == "hello_world"

    def test_multiple_underscores_collapsed(self, tmp_path):
        cm = CacheManager("test")
        key = cm.get_cache_key({"text": "hello___world"})
        assert key == "hello_world"

    def test_leading_trailing_underscores_stripped(self, tmp_path):
        cm = CacheManager("test")
        key = cm.get_cache_key({"text": "  hello  "})
        assert key == "hello"
        assert not key.startswith("_")
        assert not key.endswith("_")

    def test_result_is_lowercase(self, tmp_path):
        cm = CacheManager("test")
        key = cm.get_cache_key({"text": "Hello WORLD"})
        assert key == "hello_world"

    def test_empty_string_value_ignored(self, tmp_path):
        """Empty/whitespace-only strings are excluded from text values."""
        cm = CacheManager("test")
        key = cm.get_cache_key({"a": "", "b": "hello"})
        assert key == "hello"

    def test_whitespace_only_string_ignored(self, tmp_path):
        cm = CacheManager("test")
        key = cm.get_cache_key({"a": "   ", "b": "world"})
        assert key == "world"

    def test_no_string_values_falls_back_to_sha256(self, tmp_path):
        cm = CacheManager("test")
        input_data = {"count": 42, "ratio": 3.14}
        key = cm.get_cache_key(input_data)
        expected = hashlib.sha256(
            json.dumps(input_data, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        assert key == expected
        assert len(key) == 64  # SHA-256 hex digest length

    def test_all_empty_strings_falls_back_to_sha256(self, tmp_path):
        cm = CacheManager("test")
        input_data = {"a": "", "b": "  "}
        key = cm.get_cache_key(input_data)
        expected = hashlib.sha256(
            json.dumps(input_data, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        assert key == expected

    def test_non_string_values_skipped(self, tmp_path):
        cm = CacheManager("test")
        key = cm.get_cache_key({"num": 99, "text": "keep"})
        assert key == "keep"

    def test_pipe_separator_between_values(self, tmp_path):
        """Multiple string values are joined with ' | ' before sanitization."""
        cm = CacheManager("test")
        key = cm.get_cache_key({"a": "first", "b": "second"})
        # ' | ' becomes '_' after sanitization (pipe removed, spaces collapsed)
        assert key == "first_second"

    def test_very_long_text(self, tmp_path):
        cm = CacheManager("test")
        long_text = "a" * 5000
        key = cm.get_cache_key({"text": long_text})
        assert key == long_text  # all lowercase 'a' characters pass through

    def test_composed_vs_decomposed_unicode(self, tmp_path):
        """Pre-composed and decomposed forms produce the same key."""
        cm = CacheManager("test")
        # U+00E9 (composed e-acute) vs U+0065 U+0301 (decomposed)
        key_composed = cm.get_cache_key({"t": "\u00e9"})
        key_decomposed = cm.get_cache_key({"t": "e\u0301"})
        assert key_composed == key_decomposed == "e"


# ---------------------------------------------------------------------------
# JSON set / get round-trip
# ---------------------------------------------------------------------------


class TestJsonRoundTrip:
    def test_set_and_get_dict(self, tmp_path):
        cm = CacheManager("test")
        data = {"answer": 42, "nested": {"key": "value"}}
        input_data = {"query": "meaning of life"}

        cm.set("my_func", input_data, data)
        result = cm.get("my_func", input_data)

        assert result == data

    def test_set_and_get_list(self, tmp_path):
        cm = CacheManager("test")
        data = [1, "two", {"three": 3}]
        input_data = {"id": "listdata"}

        cm.set("func", input_data, data)
        assert cm.get("func", input_data) == data

    def test_json_file_created_on_disk(self, tmp_path):
        cm = CacheManager("sub")
        input_data = {"text": "hello"}
        cm.set("fn", input_data, {"stored": True})

        cache_key = cm.get_cache_key(input_data)
        expected_path = tmp_path / "sub" / "fn" / f"{cache_key}.json"
        assert expected_path.exists()

        with open(expected_path, "r", encoding="utf-8") as f:
            assert json.load(f) == {"stored": True}


# ---------------------------------------------------------------------------
# Binary set / get round-trip
# ---------------------------------------------------------------------------


class TestBinaryRoundTrip:
    def test_set_and_get_bytes(self, tmp_path):
        cm = CacheManager("audio")
        audio_bytes = b"\x00\x01\x02\xff" * 100
        input_data = {"text": "speak this"}

        cm.set("tts", input_data, audio_bytes, file_extension=".mp3")
        result = cm.get("tts", input_data)

        assert result == audio_bytes
        assert isinstance(result, bytes)

    def test_binary_file_created_on_disk(self, tmp_path):
        cm = CacheManager("audio")
        input_data = {"text": "test audio"}
        raw = b"\xde\xad\xbe\xef"

        cm.set("tts", input_data, raw, file_extension=".wav")

        cache_key = cm.get_cache_key(input_data)
        expected_path = tmp_path / "audio" / "tts" / f"{cache_key}.wav"
        assert expected_path.exists()

        with open(expected_path, "rb") as f:
            assert f.read() == raw


# ---------------------------------------------------------------------------
# Memory cache hit (no disk read needed)
# ---------------------------------------------------------------------------


class TestMemoryCacheHit:
    def test_memory_hit_without_disk_access(self, tmp_path):
        cm = CacheManager("test")
        input_data = {"text": "cached"}
        cm.set("fn", input_data, {"value": 1})

        # The value is now in memory. Even if we delete the disk file,
        # get() should still return the cached result.
        cache_key = cm.get_cache_key(input_data)
        disk_file = tmp_path / "test" / "fn" / f"{cache_key}.json"
        disk_file.unlink()

        result = cm.get("fn", input_data)
        assert result == {"value": 1}

    def test_set_updates_memory_immediately(self, tmp_path):
        cm = CacheManager("test")
        input_data = {"text": "val"}

        cm.set("fn", input_data, {"v": 1})
        assert cm._cache[cm.get_cache_key(input_data)] == {"v": 1}

        cm.set("fn", input_data, {"v": 2})
        assert cm._cache[cm.get_cache_key(input_data)] == {"v": 2}


# ---------------------------------------------------------------------------
# Disk fallback when memory is empty
# ---------------------------------------------------------------------------


class TestDiskFallback:
    def test_disk_fallback_after_memory_cleared(self, tmp_path):
        cm = CacheManager("test")
        input_data = {"text": "persist"}
        cm.set("fn", input_data, {"on_disk": True})

        # Clear the in-memory cache to force a disk read
        cm._cache.clear()

        result = cm.get("fn", input_data)
        assert result == {"on_disk": True}

    def test_disk_fallback_populates_memory(self, tmp_path):
        cm = CacheManager("test")
        input_data = {"text": "reload"}
        cm.set("fn", input_data, {"loaded": True})

        cache_key = cm.get_cache_key(input_data)
        cm._cache.clear()
        assert cache_key not in cm._cache

        cm.get("fn", input_data)
        assert cache_key in cm._cache
        assert cm._cache[cache_key] == {"loaded": True}

    def test_disk_fallback_for_binary(self, tmp_path):
        cm = CacheManager("test")
        input_data = {"text": "audio"}
        raw = b"\x01\x02\x03"
        cm.set("fn", input_data, raw, file_extension=".mp3")

        cm._cache.clear()

        result = cm.get("fn", input_data)
        assert result == raw
        assert isinstance(result, bytes)


# ---------------------------------------------------------------------------
# get_by_key
# ---------------------------------------------------------------------------


class TestGetByKey:
    def test_get_by_key_from_memory(self, tmp_path):
        cm = CacheManager("test")
        input_data = {"text": "lookup"}
        cm.set("fn", input_data, {"found": True})

        cache_key = cm.get_cache_key(input_data)
        result = cm.get_by_key(cache_key)
        assert result == {"found": True}

    def test_get_by_key_from_disk(self, tmp_path):
        cm = CacheManager("test")
        input_data = {"text": "disklookup"}
        cm.set("fn", input_data, {"disk": True})

        cache_key = cm.get_cache_key(input_data)
        cm._cache.clear()

        result = cm.get_by_key(cache_key)
        assert result == {"disk": True}

    def test_get_by_key_returns_none_for_missing(self, tmp_path):
        cm = CacheManager("test")
        assert cm.get_by_key("nonexistent_key") is None

    def test_get_by_key_populates_memory(self, tmp_path):
        cm = CacheManager("test")
        input_data = {"text": "populate"}
        cm.set("fn", input_data, {"cached": True})

        cache_key = cm.get_cache_key(input_data)
        cm._cache.clear()

        cm.get_by_key(cache_key)
        assert cache_key in cm._cache


# ---------------------------------------------------------------------------
# _load_all on init
# ---------------------------------------------------------------------------


class TestLoadAll:
    def test_loads_existing_json_files_on_init(self, tmp_path):
        # Pre-populate the disk cache before creating the CacheManager
        func_dir = tmp_path / "preloaded" / "my_func"
        func_dir.mkdir(parents=True)
        with open(func_dir / "existing_key.json", "w", encoding="utf-8") as f:
            json.dump({"preloaded": True}, f)

        cm = CacheManager("preloaded")
        assert cm._cache["existing_key"] == {"preloaded": True}

    def test_loads_existing_binary_files_on_init(self, tmp_path):
        func_dir = tmp_path / "binload" / "tts"
        func_dir.mkdir(parents=True)
        with open(func_dir / "audio_key.mp3", "wb") as f:
            f.write(b"\xff\xd8\xff")

        cm = CacheManager("binload")
        assert cm._cache["audio_key"] == b"\xff\xd8\xff"

    def test_loads_multiple_functions(self, tmp_path):
        for func_name in ("func_a", "func_b"):
            func_dir = tmp_path / "multi" / func_name
            func_dir.mkdir(parents=True)
            with open(func_dir / f"{func_name}_key.json", "w") as f:
                json.dump({"func": func_name}, f)

        cm = CacheManager("multi")
        assert cm._cache["func_a_key"] == {"func": "func_a"}
        assert cm._cache["func_b_key"] == {"func": "func_b"}

    def test_creates_root_folder_if_missing(self, tmp_path):
        subfolder = tmp_path / "brand_new"
        assert not subfolder.exists()

        cm = CacheManager("brand_new")
        assert subfolder.exists()
        assert cm._cache == {}

    def test_skips_non_directory_entries(self, tmp_path):
        root = tmp_path / "mixed"
        root.mkdir()
        # Place a file directly in root (not in a subdirectory)
        (root / "stray_file.txt").write_text("not a cache dir")

        func_dir = root / "real_func"
        func_dir.mkdir()
        with open(func_dir / "key.json", "w") as f:
            json.dump({"valid": True}, f)

        cm = CacheManager("mixed")
        assert cm._cache["key"] == {"valid": True}
        assert "stray_file" not in cm._cache

    def test_skips_non_file_entries_in_function_dir(self, tmp_path):
        func_dir = tmp_path / "nested" / "fn"
        func_dir.mkdir(parents=True)
        # Create a subdirectory inside the function directory
        (func_dir / "subdir").mkdir()
        with open(func_dir / "valid.json", "w") as f:
            json.dump({"ok": True}, f)

        cm = CacheManager("nested")
        assert cm._cache["valid"] == {"ok": True}


# ---------------------------------------------------------------------------
# Cache miss
# ---------------------------------------------------------------------------


class TestCacheMiss:
    def test_get_returns_none_for_missing_key(self, tmp_path):
        cm = CacheManager("test")
        result = cm.get("fn", {"text": "never stored"})
        assert result is None

    def test_get_returns_none_for_wrong_function_on_disk(self, tmp_path):
        """When memory is empty, get() only searches the target function dir."""
        cm = CacheManager("test")
        cm.set("fn_a", {"text": "stored"}, {"data": True})

        # Clear memory so get() must fall back to disk
        cm._cache.clear()

        # Same input_data but different function_name -- the file lives
        # under fn_a/ on disk, so fn_b/ will not find it.
        result = cm.get("fn_b", {"text": "stored"})
        assert result is None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_dict_input(self, tmp_path):
        cm = CacheManager("test")
        key = cm.get_cache_key({})
        # No string values, falls back to SHA-256
        expected = hashlib.sha256(b"{}").hexdigest()
        assert key == expected

    def test_dict_with_only_numeric_values(self, tmp_path):
        cm = CacheManager("test")
        input_data = {"x": 1, "y": 2, "z": 3}
        key = cm.get_cache_key(input_data)
        expected = hashlib.sha256(
            json.dumps(input_data, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        assert key == expected

    def test_set_and_get_with_numeric_only_input(self, tmp_path):
        cm = CacheManager("test")
        input_data = {"temperature": 0.7, "max_tokens": 100}
        cm.set("llm", input_data, {"response": "ok"})

        result = cm.get("llm", input_data)
        assert result == {"response": "ok"}

    def test_unicode_in_json_values(self, tmp_path):
        cm = CacheManager("test")
        data = {"message": "Guten Tag, wie geht es Ihnen?"}
        cm.set("fn", {"text": "greeting"}, data)

        result = cm.get("fn", {"text": "greeting"})
        assert result == data

    def test_different_subfolders_are_isolated(self, tmp_path):
        cm_a = CacheManager("service_a")
        cm_b = CacheManager("service_b")

        cm_a.set("fn", {"text": "shared"}, {"from": "a"})
        cm_b.set("fn", {"text": "shared"}, {"from": "b"})

        assert cm_a.get("fn", {"text": "shared"}) == {"from": "a"}
        assert cm_b.get("fn", {"text": "shared"}) == {"from": "b"}

    def test_overwrite_existing_cache_entry(self, tmp_path):
        cm = CacheManager("test")
        input_data = {"text": "overwrite me"}

        cm.set("fn", input_data, {"version": 1})
        assert cm.get("fn", input_data) == {"version": 1}

        cm.set("fn", input_data, {"version": 2})
        assert cm.get("fn", input_data) == {"version": 2}

    def test_cache_key_deterministic(self, tmp_path):
        cm = CacheManager("test")
        input_data = {"text": "stable key"}
        key1 = cm.get_cache_key(input_data)
        key2 = cm.get_cache_key(input_data)
        assert key1 == key2

    def test_empty_bytes(self, tmp_path):
        cm = CacheManager("test")
        cm.set("fn", {"text": "empty"}, b"", file_extension=".bin")
        result = cm.get("fn", {"text": "empty"})
        assert result == b""

    def test_new_manager_sees_previous_writes(self, tmp_path):
        """A second CacheManager instance loads files written by the first."""
        cm1 = CacheManager("shared")
        cm1.set("fn", {"text": "persist"}, {"survives": True})

        cm2 = CacheManager("shared")
        assert cm2.get("fn", {"text": "persist"}) == {"survives": True}
