import hashlib
import json
import logging
import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

root_cache_folder = Path(os.getenv("CACHE_ROOT", "./cache"))


class CacheManager:
    """
    A cache manager that loads all cached files into memory for fast access.
    Supports different file types, adaptable to audio files and JSON data.
    """

    def __init__(self, root_folder: str):
        self.root_folder = root_cache_folder / Path(root_folder)
        self.cache: Dict[str, Any] = {}
        self._load_all_cache()

    def _load_all_cache(self):
        """Load all cached files into the in-memory dict."""
        if not self.root_folder.exists():
            self.root_folder.mkdir(parents=True, exist_ok=True)
            return

        for cache_dir in self.root_folder.iterdir():
            if cache_dir.is_dir():
                for cache_file in cache_dir.iterdir():
                    if cache_file.is_file():
                        try:
                            if cache_file.suffix == ".json":
                                with open(cache_file, "r", encoding="utf-8") as f:
                                    data = json.load(f)
                                self.cache[cache_file.stem] = data
                            elif cache_file.suffix in [
                                ".wav",
                                ".mp3",
                                ".ogg",
                                ".flac",
                            ]:  # Audio files
                                with open(cache_file, "rb") as f:
                                    data = f.read()
                                self.cache[cache_file.stem] = data
                            else:
                                # For other files, store as binary
                                with open(cache_file, "rb") as f:
                                    data = f.read()
                                self.cache[cache_file.stem] = data
                        except Exception as e:
                            logger.warning(
                                f"Error loading cache file {cache_file}: {e}"
                            )

    def _get_cache_dir(self, function_name: str) -> Path:
        """Get or create cache directory for a specific function."""
        cache_dir = self.root_folder / function_name
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    def get_cache_key(self, input_data: dict) -> str:
        """Generate a cache key from input data by sanitizing all text values."""
        # Collect all text values from the input data
        text_values = []
        for key in sorted(input_data.keys()):  # Sort for consistency
            value = input_data[key]
            if isinstance(value, str) and value.strip():  # Only non-empty strings
                text_values.append(value)

        if not text_values:
            # Fallback to hash if no text found
            data_str = json.dumps(input_data, sort_keys=True, ensure_ascii=False)
            return hashlib.sha256(data_str.encode()).hexdigest()

        # Combine all text values with a separator
        combined_text = " | ".join(text_values)

        # Normalize unicode and remove accents/umlauts (optimized: use str.translate for faster removal)
        normalized = unicodedata.normalize("NFD", combined_text)
        trans_table = dict.fromkeys(
            c for c in range(128) if unicodedata.category(chr(c)) == "Mn"
        )
        without_accents = normalized.translate(trans_table)

        # Replace spaces with underscores and remove all punctuation (optimized: combine regex)
        sanitized = re.sub(
            r"[^a-zA-Z0-9_ ]", "", without_accents
        )  # Remove punctuation (note: space instead of \s for speed)
        sanitized = re.sub(r" +", "_", sanitized)  # Replace spaces with underscores
        sanitized = re.sub(
            r"_+", "_", sanitized
        )  # Replace multiple underscores with single
        sanitized = sanitized.strip(
            "_"
        ).lower()  # Remove leading/trailing underscores and lowercase

        return sanitized

    def get(self, function_name: str, input_data: dict) -> Optional[Any]:
        """Retrieve cached result if it exists."""
        cache_key = self.get_cache_key(input_data)
        if cache_key in self.cache:
            return self.cache[cache_key]
        return None

    def set(
        self,
        function_name: str,
        input_data: dict,
        result: Any,
        file_extension: str = ".json",
    ) -> None:
        """Store result in cache."""
        cache_dir = self._get_cache_dir(function_name)
        cache_key = self.get_cache_key(input_data)
        cache_file = cache_dir / f"{cache_key}{file_extension}"

        try:
            if file_extension == ".json":
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
                self.cache[cache_key] = result
            else:
                # For binary data like audio
                with open(cache_file, "wb") as f:
                    f.write(result)
                self.cache[cache_key] = result
            logger.debug(f"Cache stored for {function_name} with key {cache_key}")
        except Exception as e:
            logger.warning(f"Error writing cache for {function_name}: {e}")
