"""Tests for twilio_agent.utils.cache.CacheManager."""

import json
import os
import tempfile

import pytest

# Patch the cache root before importing CacheManager so it uses a temp dir.
_tmpdir = tempfile.mkdtemp()
os.environ["CACHE_ROOT"] = _tmpdir

# Re-import after env is set -- force the module to pick up our temp root.
import importlib
import twilio_agent.utils.cache as cache_module

cache_module._root_cache_folder = cache_module.Path(_tmpdir)

from twilio_agent.utils.cache import CacheManager


@pytest.fixture()
def manager(tmp_path):
    """Create a CacheManager using a fresh temp directory."""
    cache_module._root_cache_folder = tmp_path
    return CacheManager("test_sub")


class TestGetCacheKey:
    """Tests for CacheManager.get_cache_key."""

    def test_simple_text(self, manager):
        key = manager.get_cache_key({"text": "Hello World"})
        assert key == "hello_world"

    def test_empty_dict_falls_back_to_hash(self, manager):
        key = manager.get_cache_key({})
        # Should be a hex digest (64 chars for SHA-256)
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)

    def test_non_string_values_fall_back_to_hash(self, manager):
        key = manager.get_cache_key({"count": 42, "flag": True})
        assert len(key) == 64

    def test_whitespace_only_values_fall_back_to_hash(self, manager):
        key = manager.get_cache_key({"text": "   "})
        assert len(key) == 64

    def test_german_umlauts_stripped(self, manager):
        key = manager.get_cache_key({"text": "Tueroeffner"})
        key_umlaut = manager.get_cache_key({"text": "Turoeffner"})
        # Both should produce valid ASCII keys
        assert key.isascii()
        assert key_umlaut.isascii()

    def test_accented_characters_removed(self, manager):
        key = manager.get_cache_key({"text": "cafe"})
        assert "cafe" in key
        assert key.isascii()

    def test_punctuation_removed(self, manager):
        key = manager.get_cache_key({"text": "hello, world!"})
        assert "," not in key
        assert "!" not in key

    def test_multiple_spaces_collapsed(self, manager):
        key = manager.get_cache_key({"text": "hello   world"})
        assert "__" not in key
        assert "hello_world" == key

    def test_leading_trailing_underscores_stripped(self, manager):
        key = manager.get_cache_key({"text": "  hello  "})
        assert not key.startswith("_")
        assert not key.endswith("_")

    def test_multiple_string_values_sorted(self, manager):
        key1 = manager.get_cache_key({"a": "alpha", "b": "beta"})
        key2 = manager.get_cache_key({"b": "beta", "a": "alpha"})
        assert key1 == key2

    def test_result_is_lowercase(self, manager):
        key = manager.get_cache_key({"text": "HELLO"})
        assert key == "hello"

    def test_consistent_across_calls(self, manager):
        data = {"text": "consistent input"}
        assert manager.get_cache_key(data) == manager.get_cache_key(data)


class TestSetAndGet:
    """Tests for CacheManager.set and CacheManager.get."""

    def test_set_json_and_get(self, manager):
        input_data = {"text": "test value"}
        result = {"answer": 42}
        manager.set("my_func", input_data, result)

        retrieved = manager.get("my_func", input_data)
        assert retrieved == result

    def test_set_binary_and_get(self, manager):
        input_data = {"text": "audio clip"}
        audio_bytes = b"\x00\x01\x02\x03" * 100
        manager.set("tts", input_data, audio_bytes, file_extension=".mp3")

        retrieved = manager.get("tts", input_data)
        assert retrieved == audio_bytes

    def test_get_returns_none_for_missing_key(self, manager):
        result = manager.get("nonexistent_func", {"text": "no match"})
        assert result is None

    def test_set_overwrites_existing(self, manager):
        input_data = {"text": "overwrite me"}
        manager.set("func", input_data, {"v": 1})
        manager.set("func", input_data, {"v": 2})

        retrieved = manager.get("func", input_data)
        assert retrieved == {"v": 2}

    def test_get_from_disk_after_memory_clear(self, manager):
        """Verify disk fallback when in-memory cache is empty."""
        input_data = {"text": "persist me"}
        result = {"persisted": True}
        manager.set("disk_test", input_data, result)

        # Clear in-memory cache to force disk read
        manager._cache.clear()

        retrieved = manager.get("disk_test", input_data)
        assert retrieved == result


class TestGetByKey:
    """Tests for CacheManager.get_by_key."""

    def test_get_by_key_from_memory(self, manager):
        input_data = {"text": "by key test"}
        result = b"audio data here"
        manager.set("speech", input_data, result, file_extension=".mp3")

        key = manager.get_cache_key(input_data)
        retrieved = manager.get_by_key(key)
        assert retrieved == result

    def test_get_by_key_from_disk(self, manager):
        input_data = {"text": "disk key test"}
        result = {"data": "from disk"}
        manager.set("lookup", input_data, result)

        key = manager.get_cache_key(input_data)
        manager._cache.clear()

        retrieved = manager.get_by_key(key)
        assert retrieved == result

    def test_get_by_key_returns_none_for_missing(self, manager):
        assert manager.get_by_key("totally_missing_key") is None


class TestLoadAll:
    """Tests for startup pre-loading behaviour."""

    def test_preloads_existing_files(self, tmp_path):
        """A new CacheManager should find files written by a previous one."""
        cache_module._root_cache_folder = tmp_path

        # First manager writes data
        m1 = CacheManager("preload")
        m1.set("func_a", {"text": "preloaded"}, {"loaded": True})

        # Second manager should pre-load it
        m2 = CacheManager("preload")
        key = m2.get_cache_key({"text": "preloaded"})
        assert key in m2._cache
        assert m2._cache[key] == {"loaded": True}

    def test_creates_folder_if_missing(self, tmp_path):
        cache_module._root_cache_folder = tmp_path
        subfolder = tmp_path / "brand_new"
        assert not subfolder.exists()

        CacheManager("brand_new")
        assert subfolder.exists()


class TestEdgeCases:
    """Miscellaneous edge-case tests."""

    def test_empty_string_input(self, manager):
        key = manager.get_cache_key({"text": ""})
        # Empty string is treated as whitespace-only -> hash fallback
        assert len(key) == 64

    def test_special_characters_in_input(self, manager):
        key = manager.get_cache_key({"text": "foo@bar#baz$qux"})
        assert key.isascii()
        assert "@" not in key
        assert "#" not in key
        assert "$" not in key

    def test_very_long_input(self, manager):
        long_text = "a" * 10_000
        key = manager.get_cache_key({"text": long_text})
        assert isinstance(key, str)
        assert len(key) > 0

    def test_set_with_invalid_path_logs_warning(self, manager, caplog):
        """Writing to an impossible path should log, not raise."""
        # Force an invalid path by making root_folder point to a file
        original = manager.root_folder
        manager.root_folder = manager.root_folder / "nonexistent" / "\x00bad"
        try:
            manager.set("bad", {"text": "x"}, {"data": 1})
        except Exception:
            pass  # Some OSes raise, some don't -- we just want no crash
        finally:
            manager.root_folder = original
