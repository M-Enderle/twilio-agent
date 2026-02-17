"""Integration tests for the public API of twilio_agent.utils.ai.

Tests the four public functions end-to-end with real LLM calls (no mocking).
Tests that require API keys are skipped when ``XAI_API_KEY`` is not set.
"""

import os

import pytest

from twilio_agent.utils.ai import (
    classify_intent,
    correct_plz,
    process_location,
    yes_no_question,
)

VALID_INTENTS = {"schlüsseldienst", "abschleppdienst", "adac", "mitarbeiter", "andere"}

requires_api = pytest.mark.skipif(
    not os.environ.get("XAI_API_KEY"),
    reason="XAI_API_KEY not set",
)


# ---------------------------------------------------------------------------
# classify_intent
# ---------------------------------------------------------------------------
class TestClassifyIntent:
    @pytest.mark.asyncio
    async def test_empty_text(self):
        classification, reasoning, duration, source = await classify_intent("")
        assert classification == "andere"
        assert reasoning == "Kein Text vorhanden."
        assert duration is None
        assert source == "cache"

    @requires_api
    @pytest.mark.asyncio
    async def test_return_shape(self):
        result = await classify_intent("Mein Auto springt nicht an")
        assert isinstance(result, tuple) and len(result) == 4
        classification, reasoning, duration, source = result
        assert isinstance(classification, str)
        assert isinstance(reasoning, str)
        assert duration is None or isinstance(duration, float)
        assert isinstance(source, str)

    @requires_api
    @pytest.mark.asyncio
    async def test_classification_in_valid_set(self):
        classification, *_ = await classify_intent("Ich brauche einen Schlüsseldienst")
        assert classification in VALID_INTENTS

    @requires_api
    @pytest.mark.asyncio
    async def test_auto_panne(self):
        classification, *_ = await classify_intent("Mein Auto springt nicht an, ich brauche Hilfe")
        assert classification == "abschleppdienst"

    @requires_api
    @pytest.mark.asyncio
    async def test_schluessel_verloren(self):
        classification, *_ = await classify_intent("Ich habe meinen Schlüssel verloren und komme nicht in die Wohnung")
        assert classification == "schlüsseldienst"

    @requires_api
    @pytest.mark.asyncio
    async def test_adac(self):
        classification, *_ = await classify_intent("Ich möchte den ADAC erreichen")
        assert classification == "adac"

    @requires_api
    @pytest.mark.asyncio
    async def test_mitarbeiter(self):
        classification, *_ = await classify_intent("Kann ich bitte mit einem Mitarbeiter sprechen?")
        assert classification == "mitarbeiter"

    @requires_api
    @pytest.mark.asyncio
    async def test_andere_vague(self):
        classification, *_ = await classify_intent("Was kostet das?")
        assert classification == "andere"


# ---------------------------------------------------------------------------
# yes_no_question
# ---------------------------------------------------------------------------
class TestYesNoQuestion:
    @pytest.mark.asyncio
    async def test_empty_text(self):
        is_yes, reasoning, duration, source = await yes_no_question("", "context")
        assert is_yes is False
        assert reasoning == "Kein Text vorhanden."
        assert duration is None
        assert source == "cache"

    @requires_api
    @pytest.mark.asyncio
    async def test_return_shape(self):
        result = await yes_no_question("ja gerne", "Möchten Sie fortfahren?")
        assert isinstance(result, tuple) and len(result) == 4
        is_yes, reasoning, duration, source = result
        assert isinstance(is_yes, bool)
        assert isinstance(reasoning, str)
        assert duration is None or isinstance(duration, float)
        assert isinstance(source, str)

    @requires_api
    @pytest.mark.asyncio
    async def test_clear_yes(self):
        is_yes, *_ = await yes_no_question("Ja, genau, das stimmt", "Ist das korrekt?")
        assert is_yes is True

    @requires_api
    @pytest.mark.asyncio
    async def test_clear_no(self):
        is_yes, *_ = await yes_no_question("Nein, auf keinen Fall", "Möchten Sie fortfahren?")
        assert is_yes is False


# ---------------------------------------------------------------------------
# process_location
# ---------------------------------------------------------------------------
class TestProcessLocation:
    @pytest.mark.asyncio
    async def test_empty_text(self):
        result = await process_location("")
        assert result == (None, None, None, None, 0.0, "cache")

    @requires_api
    @pytest.mark.asyncio
    async def test_return_shape(self):
        result = await process_location("Hauptstraße 5 in 87509 Immenstadt")
        assert isinstance(result, tuple) and len(result) == 6
        contains_loc, contains_city, knows_loc, address, duration, source = result
        assert isinstance(contains_loc, bool) or contains_loc is None
        assert isinstance(contains_city, bool) or contains_city is None
        assert isinstance(knows_loc, bool) or knows_loc is None
        assert address is None or isinstance(address, str)
        assert isinstance(duration, float)
        assert isinstance(source, str)

    @requires_api
    @pytest.mark.asyncio
    async def test_full_address(self):
        contains_loc, contains_city, knows_loc, address, *_ = await process_location(
            "Hauptstraße 5 in 87509 Immenstadt"
        )
        assert contains_loc is True
        assert contains_city is True
        assert address is not None

    @requires_api
    @pytest.mark.asyncio
    async def test_no_location(self):
        contains_loc, *_ = await process_location("Ich weiß nicht wo ich bin")
        assert contains_loc is False

    @requires_api
    @pytest.mark.asyncio
    async def test_city_only(self):
        contains_loc, contains_city, _, address, *_ = await process_location("Ich bin in München")
        assert contains_loc is True
        assert contains_city is True


# ---------------------------------------------------------------------------
# correct_plz
# ---------------------------------------------------------------------------
class TestCorrectPlz:
    @pytest.mark.asyncio
    async def test_empty_location(self):
        assert await correct_plz("", 48.0, 14.0) is None

    @requires_api
    @pytest.mark.asyncio
    async def test_return_type(self):
        result = await correct_plz("München", 48.1351, 11.582)
        assert result is None or (isinstance(result, str) and result.isdigit() and 4 <= len(result) <= 5)

    @requires_api
    @pytest.mark.asyncio
    async def test_known_city(self):
        result = await correct_plz("Immenstadt", 47.5609, 10.2173)
        # May return None on timeout (5s limit with web search); valid if it does return
        if result is not None:
            assert result.isdigit() and 4 <= len(result) <= 5
