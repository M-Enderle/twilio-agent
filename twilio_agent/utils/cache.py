"""File-backed cache with in-memory acceleration.

Stores cached results as files on disk (JSON for structured data, raw bytes
for audio) and keeps them in a ``dict`` for fast repeated access. Used by
the TTS pipeline (``eleven.py``) and LLM utilities (``ai.py``).

Disk layout::

    <CACHE_ROOT>/<subfolder>/<function_name>/<cache_key>.<ext>
"""

import hashlib
import json
import logging
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_root_cache_folder = Path(os.getenv("CACHE_ROOT", "./cache"))


class CacheManager:
    """File-backed cache that pre-loads entries into memory at startup.

    Each instance manages a subfolder under the global cache root. Files
    are organised into per-function subdirectories so that different
    callers (e.g. ``generate_speech``, ``classify_intent``) do not
    collide.
    """

    def __init__(self, subfolder: str) -> None:
        self.root_folder: Path = _root_cache_folder / subfolder
        self._cache: dict[str, Any] = {}
        self._load_all()

    @staticmethod
    def _read_file(path: Path) -> Any:
        """Read a single cache file and return its contents.

        JSON files are deserialised; everything else is returned as raw
        ``bytes``.
        """
        if path.suffix == ".json":
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        with open(path, "rb") as f:
            return f.read()

    def _load_all(self) -> None:
        """Load every cached file into memory at startup."""
        if not self.root_folder.exists():
            self.root_folder.mkdir(parents=True, exist_ok=True)
            return

        for cache_dir in self.root_folder.iterdir():
            if not cache_dir.is_dir():
                continue
            for cache_file in cache_dir.iterdir():
                if not cache_file.is_file():
                    continue
                try:
                    self._cache[cache_file.stem] = self._read_file(
                        cache_file,
                    )
                except Exception as e:
                    logger.warning(
                        "Error loading cache file %s: %s", cache_file, e,
                    )

    def _get_cache_dir(self, function_name: str) -> Path:
        """Return the subdirectory for *function_name*, creating it if needed."""
        cache_dir = self.root_folder / function_name
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    def get_cache_key(self, input_data: dict) -> str:
        """Generate a filesystem-safe cache key from *input_data*.

        Non-empty string values are extracted (in sorted-key order),
        normalised to ASCII, and joined with underscores to produce a
        human-readable key.  When no string values are present the key
        falls back to a SHA-256 hex digest.

        Args:
            input_data: Arbitrary dict whose string values identify the
                cached entry.

        Returns:
            A sanitised, lowercase string usable as a filename stem.
        """
        text_values = [
            value
            for key in sorted(input_data.keys())
            if isinstance((value := input_data[key]), str) and value.strip()
        ]

        if not text_values:
            data_str = json.dumps(
                input_data, sort_keys=True, ensure_ascii=False,
            )
            return hashlib.sha256(data_str.encode()).hexdigest()

        combined_text = " | ".join(text_values)

        # Decompose unicode and strip all combining marks (Mn category)
        # so that e.g. "u" + U+0308 (from "ue") is reduced to plain "u".
        normalized = unicodedata.normalize("NFD", combined_text)
        without_accents = "".join(
            ch for ch in normalized
            if unicodedata.category(ch) != "Mn"
        )

        sanitized = re.sub(r"[^a-zA-Z0-9_ ]", "", without_accents)
        sanitized = re.sub(r"[ _]+", "_", sanitized)
        sanitized = sanitized.strip("_").lower()

        return sanitized

    def get(self, function_name: str, input_data: dict) -> Any | None:
        """Retrieve a cached result, checking memory first then disk.

        Args:
            function_name: Subdirectory name (typically the calling
                function's name).
            input_data: Dict used to derive the cache key.

        Returns:
            The cached value, or ``None`` if no entry exists.
        """
        cache_key = self.get_cache_key(input_data)
        if cache_key in self._cache:
            return self._cache[cache_key]

        cache_dir = self._get_cache_dir(function_name)
        for cache_file in cache_dir.iterdir():
            if cache_file.is_file() and cache_file.stem == cache_key:
                try:
                    data = self._read_file(cache_file)
                    self._cache[cache_key] = data
                    return data
                except Exception as e:
                    logger.warning(
                        "Error loading cache file %s: %s", cache_file, e,
                    )

        logger.info("No cached result found for %s", function_name)
        return None

    def set(
        self,
        function_name: str,
        input_data: dict,
        result: Any,
        file_extension: str = ".json",
    ) -> None:
        """Write *result* to both disk and the in-memory cache.

        Args:
            function_name: Subdirectory name for the cached file.
            input_data: Dict used to derive the cache key.
            result: Data to cache (``dict`` for JSON, ``bytes`` for binary).
            file_extension: File suffix including the dot (e.g. ``".mp3"``).
        """
        cache_dir = self._get_cache_dir(function_name)
        cache_key = self.get_cache_key(input_data)
        cache_file = cache_dir / f"{cache_key}{file_extension}"

        try:
            if file_extension == ".json":
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
            else:
                with open(cache_file, "wb") as f:
                    f.write(result)
            self._cache[cache_key] = result
            logger.debug(
                "Cache stored for %s with key %s", function_name, cache_key,
            )
        except Exception as e:
            logger.warning(
                "Error writing cache for %s: %s", function_name, e,
            )

    def get_by_key(self, key: str) -> Any | None:
        """Retrieve a cached entry by its raw key (no hashing).

        Checks the in-memory cache first, then walks all subdirectories
        on disk.

        Args:
            key: The exact cache key (filename stem) to look up.

        Returns:
            The cached value, or ``None`` if not found.
        """
        if key in self._cache:
            return self._cache[key]

        if not self.root_folder.exists():
            return None

        for cache_dir in self.root_folder.iterdir():
            if not cache_dir.is_dir():
                continue
            for cache_file in cache_dir.iterdir():
                if cache_file.is_file() and cache_file.stem == key:
                    try:
                        data = self._read_file(cache_file)
                        self._cache[key] = data
                        return data
                    except Exception as e:
                        logger.warning(
                            "Error loading cache file %s: %s",
                            cache_file,
                            e,
                        )
        return None
