"""Tests for twilio_agent.utils.ai module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from twilio_agent.settings import HumanAgentRequested
from twilio_agent.utils.ai import (
    _ask_llm_parallel,
    _cached_llm_request,
    _cancel_task,
    _parse_arrow_response,
    correct_plz,
    process_location,
    yes_no_question,
)


# ---------------------------------------------------------------------------
# _parse_arrow_response
# ---------------------------------------------------------------------------


class TestParseArrowResponse:
    """Tests for the _parse_arrow_response helper."""

    def test_single_arrow_splits_into_two(self):
        result = _parse_arrow_response("Begründung -> Ja")
        assert result == ["Begründung", "Ja"]

    def test_no_arrow_returns_single_element(self):
        result = _parse_arrow_response("Just a plain response")
        assert result == ["Just a plain response"]

    def test_strips_whitespace_from_parts(self):
        result = _parse_arrow_response("  lots of space   ->   also here  ")
        assert result == ["lots of space", "also here"]

    def test_maxsplit_limits_splits(self):
        result = _parse_arrow_response("a -> b -> c -> d", maxsplit=3)
        assert result == ["a", "b", "c", "d"]

    def test_maxsplit_one_keeps_trailing_arrows(self):
        result = _parse_arrow_response("first -> second -> third", maxsplit=1)
        assert result == ["first", "second -> third"]

    def test_empty_string_returns_empty_stripped(self):
        result = _parse_arrow_response("")
        assert result == [""]

    def test_arrow_only_returns_two_empty_strings(self):
        result = _parse_arrow_response("->")
        assert result == ["", ""]

    def test_whitespace_only_no_arrow(self):
        result = _parse_arrow_response("   ")
        assert result == [""]


# ---------------------------------------------------------------------------
# _cancel_task
# ---------------------------------------------------------------------------


class TestCancelTask:
    """Tests for the _cancel_task helper."""

    @pytest.mark.asyncio
    async def test_cancels_running_task(self):
        """A running task should be cancelled without raising."""

        async def long_running():
            await asyncio.sleep(100)

        task = asyncio.create_task(long_running())
        await _cancel_task(task)
        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_cancels_already_done_task(self):
        """Cancelling an already-finished task should not raise."""

        async def instant():
            return "done"

        task = asyncio.create_task(instant())
        await task  # let it finish
        # Should not raise even though the task is already done
        await _cancel_task(task)
        assert task.done()


# ---------------------------------------------------------------------------
# yes_no_question
# ---------------------------------------------------------------------------


class TestYesNoQuestion:
    """Tests for the yes_no_question async function."""

    @pytest.mark.asyncio
    async def test_empty_text_returns_early(self):
        result = await yes_no_question("", "some context")
        assert result == (False, "Kein Text vorhanden.", None, "cache")

    @pytest.mark.asyncio
    async def test_none_text_returns_early(self):
        result = await yes_no_question(None, "some context")
        assert result == (False, "Kein Text vorhanden.", None, "cache")

    @pytest.mark.asyncio
    @patch("twilio_agent.utils.ai.cache_manager")
    @patch("twilio_agent.utils.ai._ask_llm_parallel", new_callable=AsyncMock)
    async def test_agreement_response(self, mock_llm, mock_cache):
        mock_cache.get.return_value = None
        mock_llm.return_value = ("Klar ja. -> Ja", "grok")

        is_agreement, reasoning, duration, source = await yes_no_question(
            "ja gerne", "Möchten Sie verbunden werden?"
        )

        assert is_agreement is True
        assert reasoning == "Klar ja."
        assert source == "grok"
        assert duration is not None
        mock_cache.set.assert_called_once()

    @pytest.mark.asyncio
    @patch("twilio_agent.utils.ai.cache_manager")
    @patch("twilio_agent.utils.ai._ask_llm_parallel", new_callable=AsyncMock)
    async def test_disagreement_response(self, mock_llm, mock_cache):
        mock_cache.get.return_value = None
        mock_llm.return_value = ("Klar nein. -> Nein", "gpt")

        is_agreement, reasoning, duration, source = await yes_no_question(
            "nein danke", "Möchten Sie verbunden werden?"
        )

        assert is_agreement is False
        assert reasoning == "Klar nein."
        assert source == "gpt"

    @pytest.mark.asyncio
    @patch("twilio_agent.utils.ai.cache_manager")
    @patch("twilio_agent.utils.ai._ask_llm_parallel", new_callable=AsyncMock)
    async def test_mitarbeiter_raises_human_agent_requested(
        self, mock_llm, mock_cache
    ):
        mock_cache.get.return_value = None
        mock_llm.return_value = ("MITARBEITER", "grok")

        with pytest.raises(HumanAgentRequested):
            await yes_no_question(
                "Ich möchte mit einem echten Menschen sprechen",
                "Möchten Sie verbunden werden?",
            )

    @pytest.mark.asyncio
    @patch("twilio_agent.utils.ai.cache_manager")
    async def test_cache_hit_returns_immediately(self, mock_cache):
        mock_cache.get.return_value = {
            "is_agreement": True,
            "reasoning": "Cached yes.",
            "duration": 0.5,
        }

        is_agreement, reasoning, duration, source = await yes_no_question(
            "ja", "context"
        )

        assert is_agreement is True
        assert reasoning == "Cached yes."
        assert duration == 0.0
        assert source == "cache"
        mock_cache.set.assert_not_called()

    @pytest.mark.asyncio
    @patch("twilio_agent.utils.ai.cache_manager")
    @patch("twilio_agent.utils.ai._ask_llm_parallel", new_callable=AsyncMock)
    async def test_no_arrow_in_response_uses_full_text_as_decision(
        self, mock_llm, mock_cache
    ):
        mock_cache.get.return_value = None
        mock_llm.return_value = ("Ja", "grok")

        is_agreement, reasoning, _, _ = await yes_no_question("ja", "ctx")

        assert is_agreement is True
        assert reasoning == "Keine Begründung gegeben."


# ---------------------------------------------------------------------------
# process_location
# ---------------------------------------------------------------------------


class TestProcessLocation:
    """Tests for the process_location async function."""

    @pytest.mark.asyncio
    async def test_empty_text_returns_early(self):
        result = await process_location("")
        assert result == (None, None, None, None, 0.0, "cache")

    @pytest.mark.asyncio
    async def test_none_text_returns_early(self):
        result = await process_location(None)
        assert result == (None, None, None, None, 0.0, "cache")

    @pytest.mark.asyncio
    @patch("twilio_agent.utils.ai.cache_manager")
    @patch("twilio_agent.utils.ai._ask_llm_parallel", new_callable=AsyncMock)
    async def test_full_address_extraction(self, mock_llm, mock_cache):
        mock_cache.get.return_value = None
        mock_llm.return_value = (
            "Ja -> Ja -> Ja -> Hauptstraße 5 in Immenstadt",
            "grok",
        )

        (
            contains_loc,
            contains_city,
            knows_location,
            address,
            duration,
            source,
        ) = await process_location("Hauptstraße 5 in Immenstadt")

        assert contains_loc is True
        assert contains_city is True
        assert knows_location is True
        assert address == "Hauptstraße 5 in Immenstadt"
        assert source == "grok"

    @pytest.mark.asyncio
    @patch("twilio_agent.utils.ai.cache_manager")
    @patch("twilio_agent.utils.ai._ask_llm_parallel", new_callable=AsyncMock)
    async def test_no_location_found(self, mock_llm, mock_cache):
        mock_cache.get.return_value = None
        mock_llm.return_value = ("Nein -> Nein -> Ja ->", "gpt")

        (
            contains_loc,
            contains_city,
            knows_location,
            address,
            duration,
            source,
        ) = await process_location("Ich brauche Hilfe")

        assert contains_loc is False
        assert contains_city is False
        assert knows_location is True
        assert address is None

    @pytest.mark.asyncio
    @patch("twilio_agent.utils.ai.cache_manager")
    @patch("twilio_agent.utils.ai._ask_llm_parallel", new_callable=AsyncMock)
    async def test_user_does_not_know_location(self, mock_llm, mock_cache):
        mock_cache.get.return_value = None
        mock_llm.return_value = ("Nein -> Nein -> Nein ->", "grok")

        _, _, knows_location, address, _, _ = await process_location(
            "Ich weiß nicht wo ich bin."
        )

        assert knows_location is False
        assert address is None

    @pytest.mark.asyncio
    @patch("twilio_agent.utils.ai.cache_manager")
    @patch("twilio_agent.utils.ai._ask_llm_parallel", new_callable=AsyncMock)
    async def test_mitarbeiter_raises_human_agent_requested(
        self, mock_llm, mock_cache
    ):
        mock_cache.get.return_value = None
        mock_llm.return_value = ("MITARBEITER", "grok")

        with pytest.raises(HumanAgentRequested):
            await process_location("Geben Sie mir einen Mitarbeiter")

    @pytest.mark.asyncio
    @patch("twilio_agent.utils.ai.cache_manager")
    @patch("twilio_agent.utils.ai._ask_llm_parallel", new_callable=AsyncMock)
    async def test_malformed_response_falls_back_to_no_location(
        self, mock_llm, mock_cache
    ):
        """When the LLM returns fewer than 4 parts, defaults to all Nein."""
        mock_cache.get.return_value = None
        mock_llm.return_value = ("Some unexpected text", "grok")

        contains_loc, contains_city, knows_location, address, _, _ = (
            await process_location("random text")
        )

        assert contains_loc is False
        assert contains_city is False
        assert knows_location is False
        assert address is None


# ---------------------------------------------------------------------------
# correct_plz
# ---------------------------------------------------------------------------


class TestCorrectPlz:
    """Tests for the correct_plz async function."""

    @pytest.mark.asyncio
    async def test_empty_location_returns_none(self):
        result = await correct_plz("", 48.0, 14.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_none_location_returns_none(self):
        result = await correct_plz(None, 48.0, 14.0)
        assert result is None

    @pytest.mark.asyncio
    @patch("twilio_agent.utils.ai._ask_grok", new_callable=AsyncMock)
    async def test_valid_plz_returned(self, mock_grok):
        mock_grok.return_value = "4020"

        result = await correct_plz("Linz", 48.3, 14.3)

        assert result == "4020"
        mock_grok.assert_called_once()

    @pytest.mark.asyncio
    @patch("twilio_agent.utils.ai._ask_grok", new_callable=AsyncMock)
    async def test_five_digit_plz_returned(self, mock_grok):
        mock_grok.return_value = "80331"

        result = await correct_plz("München", 48.1, 11.6)

        assert result == "80331"

    @pytest.mark.asyncio
    @patch("twilio_agent.utils.ai._ask_grok", new_callable=AsyncMock)
    async def test_non_digit_response_returns_none(self, mock_grok):
        mock_grok.return_value = "Die PLZ ist 4020"

        result = await correct_plz("Linz", 48.3, 14.3)

        assert result is None

    @pytest.mark.asyncio
    @patch("twilio_agent.utils.ai._ask_grok", new_callable=AsyncMock)
    async def test_too_short_plz_returns_none(self, mock_grok):
        mock_grok.return_value = "123"

        result = await correct_plz("Ort", 48.0, 14.0)

        assert result is None

    @pytest.mark.asyncio
    @patch("twilio_agent.utils.ai._ask_grok", new_callable=AsyncMock)
    async def test_too_long_plz_returns_none(self, mock_grok):
        mock_grok.return_value = "123456"

        result = await correct_plz("Ort", 48.0, 14.0)

        assert result is None

    @pytest.mark.asyncio
    @patch("twilio_agent.utils.ai._ask_grok", new_callable=AsyncMock)
    async def test_timeout_returns_none(self, mock_grok):
        async def slow_response(*args, **kwargs):
            await asyncio.sleep(10)
            return "4020"

        mock_grok.side_effect = slow_response

        result = await correct_plz("Linz", 48.3, 14.3)

        assert result is None

    @pytest.mark.asyncio
    @patch("twilio_agent.utils.ai._ask_grok", new_callable=AsyncMock)
    async def test_exception_returns_none(self, mock_grok):
        mock_grok.side_effect = RuntimeError("API down")

        result = await correct_plz("Linz", 48.3, 14.3)

        assert result is None

    @pytest.mark.asyncio
    @patch("twilio_agent.utils.ai._ask_grok", new_callable=AsyncMock)
    async def test_empty_response_returns_none(self, mock_grok):
        mock_grok.return_value = ""

        result = await correct_plz("Linz", 48.3, 14.3)

        assert result is None

    @pytest.mark.asyncio
    @patch("twilio_agent.utils.ai._ask_grok", new_callable=AsyncMock)
    async def test_whitespace_around_plz_is_stripped(self, mock_grok):
        mock_grok.return_value = "  4020  "

        result = await correct_plz("Linz", 48.3, 14.3)

        assert result == "4020"


# ---------------------------------------------------------------------------
# _ask_llm_parallel
# ---------------------------------------------------------------------------


class TestAskLlmParallel:
    """Tests for the _ask_llm_parallel async function."""

    @pytest.mark.asyncio
    @patch("twilio_agent.utils.ai._ask_baseten", new_callable=AsyncMock)
    @patch("twilio_agent.utils.ai._ask_grok", new_callable=AsyncMock)
    async def test_grok_wins_within_one_second(self, mock_grok, mock_baseten):
        mock_grok.return_value = "grok answer"
        mock_baseten.return_value = "baseten answer"

        result, source = await _ask_llm_parallel("system", "user")

        assert result == "grok answer"
        assert source == "grok"

    @pytest.mark.asyncio
    @patch("twilio_agent.utils.ai._ask_baseten", new_callable=AsyncMock)
    @patch("twilio_agent.utils.ai._ask_grok", new_callable=AsyncMock)
    async def test_grok_slow_and_empty_baseten_wins(
        self, mock_grok, mock_baseten
    ):
        """When grok is slow (> 1s timeout) and baseten responds first, baseten wins."""

        async def slow_empty_grok(*args, **kwargs):
            await asyncio.sleep(5)
            return ""

        mock_grok.side_effect = slow_empty_grok
        mock_baseten.return_value = "baseten answer"

        result, source = await _ask_llm_parallel("system", "user")

        assert result == "baseten answer"
        assert source == "gpt"

    @pytest.mark.asyncio
    @patch("twilio_agent.utils.ai._ask_baseten", new_callable=AsyncMock)
    @patch("twilio_agent.utils.ai._ask_grok", new_callable=AsyncMock)
    async def test_both_fail_returns_empty(self, mock_grok, mock_baseten):
        mock_grok.return_value = ""
        mock_baseten.return_value = ""

        result, source = await _ask_llm_parallel("system", "user")

        assert result == ""
        assert source == "unknown"

    @pytest.mark.asyncio
    @patch("twilio_agent.utils.ai._ask_baseten", new_callable=AsyncMock)
    @patch("twilio_agent.utils.ai._ask_grok", new_callable=AsyncMock)
    async def test_grok_slow_baseten_wins_race(
        self, mock_grok, mock_baseten
    ):
        """When grok is slow (> 1s) and returns empty, baseten wins the second race."""

        async def slow_grok(*args, **kwargs):
            await asyncio.sleep(5)
            return ""

        mock_grok.side_effect = slow_grok
        mock_baseten.return_value = "fast baseten"

        result, source = await _ask_llm_parallel("system", "user")

        assert result == "fast baseten"
        assert source == "gpt"


# ---------------------------------------------------------------------------
# _cached_llm_request
# ---------------------------------------------------------------------------


class TestCachedLlmRequest:
    """Tests for the _cached_llm_request orchestrator."""

    @pytest.mark.asyncio
    @patch("twilio_agent.utils.ai.cache_manager")
    async def test_cache_hit_returns_immediately(self, mock_cache):
        mock_cache.get.return_value = {"value": "cached", "duration": 0.1}

        result = await _cached_llm_request(
            cache_key="test_fn",
            cache_input={"text": "hello"},
            system_prompt="sys",
            user_prompt="usr",
            parse_fn=lambda r: {"value": r},
            build_return=lambda d, dur, src: (d["value"], dur, src),
            error_return=lambda e: ("error", None, "unknown"),
        )

        assert result == ("cached", 0.0, "cache")
        mock_cache.set.assert_not_called()

    @pytest.mark.asyncio
    @patch("twilio_agent.utils.ai.cache_manager")
    @patch("twilio_agent.utils.ai._ask_llm_parallel", new_callable=AsyncMock)
    async def test_cache_miss_calls_llm_and_caches(
        self, mock_llm, mock_cache
    ):
        mock_cache.get.return_value = None
        mock_llm.return_value = ("llm result", "grok")

        result = await _cached_llm_request(
            cache_key="test_fn",
            cache_input={"text": "hello"},
            system_prompt="sys",
            user_prompt="usr",
            parse_fn=lambda r: {"value": r},
            build_return=lambda d, dur, src: (d["value"], dur, src),
            error_return=lambda e: ("error", None, "unknown"),
        )

        value, duration, source = result
        assert value == "llm result"
        assert source == "grok"
        assert duration > 0 or duration == 0  # any non-negative float
        mock_cache.set.assert_called_once()

    @pytest.mark.asyncio
    @patch("twilio_agent.utils.ai.cache_manager")
    @patch("twilio_agent.utils.ai._ask_llm_parallel", new_callable=AsyncMock)
    async def test_mitarbeiter_in_response_raises(
        self, mock_llm, mock_cache
    ):
        mock_cache.get.return_value = None
        mock_llm.return_value = ("MITARBEITER", "grok")

        with pytest.raises(HumanAgentRequested):
            await _cached_llm_request(
                cache_key="test_fn",
                cache_input={"text": "give me a human"},
                system_prompt="sys",
                user_prompt="usr",
                parse_fn=lambda r: {"value": r},
                build_return=lambda d, dur, src: (d["value"], dur, src),
                error_return=lambda e: ("error", None, "unknown"),
            )

    @pytest.mark.asyncio
    @patch("twilio_agent.utils.ai.cache_manager")
    @patch("twilio_agent.utils.ai._ask_llm_parallel", new_callable=AsyncMock)
    async def test_mitarbeiter_case_insensitive(
        self, mock_llm, mock_cache
    ):
        """MITARBEITER detection should be case-insensitive."""
        mock_cache.get.return_value = None
        mock_llm.return_value = ("ich will einen Mitarbeiter bitte", "gpt")

        with pytest.raises(HumanAgentRequested):
            await _cached_llm_request(
                cache_key="test_fn",
                cache_input={"text": "test"},
                system_prompt="sys",
                user_prompt="usr",
                parse_fn=lambda r: {"value": r},
                build_return=lambda d, dur, src: (d["value"], dur, src),
                error_return=lambda e: ("error", None, "unknown"),
            )

    @pytest.mark.asyncio
    @patch("twilio_agent.utils.ai.cache_manager")
    @patch("twilio_agent.utils.ai._ask_llm_parallel", new_callable=AsyncMock)
    async def test_parse_fn_error_calls_error_return(
        self, mock_llm, mock_cache
    ):
        mock_cache.get.return_value = None
        mock_llm.return_value = ("valid text", "grok")

        def bad_parse(response):
            raise ValueError("parse failed")

        result = await _cached_llm_request(
            cache_key="test_fn",
            cache_input={"text": "hello"},
            system_prompt="sys",
            user_prompt="usr",
            parse_fn=bad_parse,
            build_return=lambda d, dur, src: (d["value"], dur, src),
            error_return=lambda e: ("error", None, "unknown"),
        )

        assert result == ("error", None, "unknown")

    @pytest.mark.asyncio
    @patch("twilio_agent.utils.ai.cache_manager")
    @patch("twilio_agent.utils.ai._ask_llm_parallel", new_callable=AsyncMock)
    async def test_llm_exception_calls_error_return(
        self, mock_llm, mock_cache
    ):
        mock_cache.get.return_value = None
        mock_llm.side_effect = RuntimeError("connection lost")

        result = await _cached_llm_request(
            cache_key="test_fn",
            cache_input={"text": "hello"},
            system_prompt="sys",
            user_prompt="usr",
            parse_fn=lambda r: {"value": r},
            build_return=lambda d, dur, src: (d["value"], dur, src),
            error_return=lambda e: ("error", None, "unknown"),
        )

        assert result == ("error", None, "unknown")
