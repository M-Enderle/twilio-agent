"""Parallel LLM request utilities with caching.

Races Grok (xAI) against GPT-OSS-120B (Baseten), preferring Grok when it
responds within 1 second. Results are cached via ``CacheManager``.
"""

import asyncio
import logging
import time
from typing import Callable

from openai import OpenAI
from xai_sdk import Client
from xai_sdk.chat import system, user
from xai_sdk.tools import web_search

from twilio_agent.utils.cache import CacheManager
from twilio_agent.settings import settings, HumanAgentRequested

logger = logging.getLogger("AI")

# Initialize AI clients
_xai_api_key = settings.env.XAI_API_KEY.get_secret_value() if settings.env.XAI_API_KEY else ""
_baseten_api_key = settings.env.BASETEN_API_KEY.get_secret_value() if settings.env.BASETEN_API_KEY else ""

client = Client(api_key=_xai_api_key)
baseten_client = OpenAI(
    api_key=_baseten_api_key,
    base_url=settings.env.BASETEN_BASE_URL,
) if _baseten_api_key else None

cache_manager = CacheManager("LLM")


def _parse_arrow_response(response: str, maxsplit: int = 1) -> list[str]:
    """Split an LLM response on ``->`` and strip each part.

    Args:
        response: Raw text returned by the LLM.
        maxsplit: Maximum number of splits (forwarded to ``str.split``).

    Returns:
        List of stripped string segments.
    """
    if "->" not in response:
        return [response.strip()]
    return [p.strip() for p in response.split("->", maxsplit)]


async def _cancel_task(task: asyncio.Task) -> None:
    """Cancel an asyncio task and suppress CancelledError."""
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def _ask_grok(system_prompt: str, user_prompt: str, use_web_search: bool = False) -> str:
    """Grok API call, run in a thread to be awaitable."""

    def _sync_call():
        try:
            tools = [web_search()] if use_web_search else None
            chat = client.chat.create(model=settings.env.XAI_MODEL, temperature=0, tools=tools)
            chat.append(system(system_prompt))
            chat.append(user(user_prompt))
            return chat.sample().content.strip()
        except Exception as e:
            logger.error("Grok API call failed: %s", e)
            return ""

    return await asyncio.to_thread(_sync_call)


async def _ask_baseten(system_prompt: str, user_prompt: str) -> str:
    """GPT-OSS-120B via Baseten, run in a thread to be awaitable."""
    if not baseten_client:
        logger.debug("Baseten client not configured.")
        return ""

    def _sync_call():
        try:
            response = baseten_client.chat.completions.create(
                model=settings.env.BASETEN_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
                max_tokens=1000,
                top_p=1,
                presence_penalty=0,
                frequency_penalty=0,
            )
            if response.choices and response.choices[0].message:
                return response.choices[0].message.content.strip()
            return ""
        except Exception as e:
            logger.debug("Baseten API call failed: %s", e)
            return ""

    return await asyncio.to_thread(_sync_call)


async def _ask_llm_parallel(system_prompt: str, user_prompt: str) -> tuple[str, str]:
    """Race Grok and Baseten. Prefers Grok if it finishes within 1s."""
    grok_task = asyncio.create_task(_ask_grok(system_prompt, user_prompt))
    baseten_task = asyncio.create_task(_ask_baseten(system_prompt, user_prompt))

    try:
        done, _ = await asyncio.wait([grok_task], timeout=1, return_when=asyncio.FIRST_COMPLETED)
        if done:
            grok_result = await grok_task
            if grok_result:
                await _cancel_task(baseten_task)
                return grok_result, "grok"
            # Grok returned empty — fall through to race both

        done_both, pending_both = await asyncio.wait(
            [grok_task, baseten_task], return_when=asyncio.FIRST_COMPLETED
        )
        finished_task = done_both.pop()
        resp = await finished_task
        model_source = "grok" if finished_task == grok_task else "gpt"
        for task in pending_both:
            await _cancel_task(task)
        return (resp, model_source) if resp else ("", "unknown")
    except Exception:
        logger.exception("Unexpected error in _ask_llm_parallel")
        return "", "unknown"
    finally:
        for task in [grok_task, baseten_task]:
            if not task.done():
                await _cancel_task(task)


async def _cached_llm_request(
    cache_key: str,
    cache_input: dict,
    system_prompt: str,
    user_prompt: str,
    parse_fn: Callable[[str], dict],
    build_return: Callable[[dict, float, str], tuple],
    error_return: Callable[[Exception], tuple],
) -> tuple:
    """Cache check -> timed LLM call -> parse -> cache set -> return.

    Each public function supplies:
      parse_fn:     raw LLM text  -> dict of result fields
      build_return: (result_dict, duration, model_source) -> final return tuple
      error_return: exception -> final return tuple on failure
    """
    cached = cache_manager.get(cache_key, cache_input)
    if cached:
        logger.info("Returning cached result for %s", cache_key)
        return build_return(cached, 0.0, "cache")

    try:
        start = time.monotonic()
        response, model_source = await _ask_llm_parallel(system_prompt, user_prompt)
        if "MITARBEITER" in response.upper():
            logger.info("Detected request for human agent in %s, overriding response.", cache_key)
            raise HumanAgentRequested("User requested human agent.")
        parsed = parse_fn(response.strip())
        duration = time.monotonic() - start
        cache_manager.set(cache_key, cache_input, {**parsed, "duration": duration})
        logger.info("%s complete. Model: %s", cache_key, model_source)
        return build_return(parsed, duration, model_source)
    except HumanAgentRequested:
        raise
    except Exception as e:
        logger.error("Error in %s: %s", cache_key, e)
        return error_return(e)


async def yes_no_question(
    spoken_text: str, context: str
) -> tuple[bool, str, float | None, str]:
    """Determine whether spoken text expresses agreement or disagreement.

    Args:
        spoken_text: Transcribed speech from the caller.
        context: Conversational context the question was asked in.

    Returns:
        A 4-tuple of ``(is_agreement, reasoning, duration, model_source)``.
    """
    if not spoken_text:
        return False, "Kein Text vorhanden.", None, "cache"

    system_prompt = """
    Entscheide, ob die Antwort Zustimmung zeigt. Gib eine kurze Begründung (max 10 Wörter) und "Ja" oder "Nein" auf Deutsch aus.

    Format: <Begründung> -> <Ja/Nein>
    Immer -> verwenden. Ohne < >.

    Ja bei Zustimmung/Bestätigung, inkl.:
    - Varianten: ja, jup, jo, genau, absolut, stimmt, passt, in Ordnung, alles klar, na gut, na ja (ohne Widerspruch), bin sicher, machen wir so.
    - Mit Nachsatz: "Stimmt, aber..." -> Ja.
    - ASR-Fehler: schwimmt (für stimmt), Jagd (für ja) bei zustimmendem Kontext.

    Nein bei:
    - Negation: nein, keineswegs, ganz und gar nicht.
    - Unklarheit: bitte wiederholen, weiß nicht, egal.
    - Verneinung: stimmt nicht, nicht richtig.
    - Frage zurück ohne Zustimmung.

    Beispiele:
    - "ja gerne" => "Klar ja. -> Ja"
    - "nein danke" => "Klar nein. -> Nein"

    SONDERREGEL:
    !! Wenn der user nach einem echten Menschen, Mitarbeiter oder Agent fragt, gebe einfach "MITARBEITER" zurück und ignoriere die Standortfrage komplett, auch wenn Standortinformationen gegeben sind. !!
    """

    def parse(response: str) -> dict:
        parts = _parse_arrow_response(response)
        if len(parts) == 2:
            reasoning, decision = parts
        else:
            decision = response
            reasoning = "Keine Begründung gegeben."
        return {"is_agreement": decision.strip().lower() == "ja", "reasoning": reasoning}

    return await _cached_llm_request(
        cache_key="yes_no_question",
        cache_input={"spoken_text": spoken_text, "context": context},
        system_prompt=system_prompt,
        user_prompt=f'Kontext: "{context}" \nAntwort des Benutzers: "{spoken_text}". Zeigt dies eine bejahende Absicht?',
        parse_fn=parse,
        build_return=lambda d, dur, src: (d["is_agreement"], d["reasoning"], dur, src),
        error_return=lambda e: (False, f"Fehler: {e}", None, "unknown"),
    )


async def process_location(
    spoken_text: str,
) -> tuple[bool | None, bool | None, bool | None, str | None, float, str]:
    """Extract location information from spoken text.

    Args:
        spoken_text: Transcribed speech from the caller.

    Returns:
        A 6-tuple of ``(contains_loc, contains_city, knows_location,
        address, duration, model_source)``.
    """
    if not spoken_text:
        return None, None, None, None, 0.0, "cache"

    system_prompt = """
    Entscheide ob der gegebene Text Standortinformationen enthält. Falls ja, entscheide ob ein Ort oder PLZ extrahiert werden kann, und extrahiere die Adresse so vollständig wie möglich.
    Gib KEINE Begründung aus. Falls nein Entscheide ob der User es nicht weiß oder ob er über etwas anderes spricht.

    Ausgabeformat (ohne zusätzliche Texte):
    <Ja/Nein> -> <Ja/Nein> -> <Ja/Nein> -> <Adresse oder Leer>
    (1. Enthält Standortinformationen? 2. Enthält Ort oder PLZ? 3. Weiß der User seine Adresse oder nicht? 4. Extrahierte Adresse)

    Enthält Standortinformationen bei jeglichen Standortinformationen, inkl.:
    - Straßenname, Hausnummer
    - Postleitzahl, Ortsname
    - Autobahnnummern mit Ortsangaben
    - Teiladressen oder nur Ortsnamen

    Enthält keine Standortinformationen bei:
    - Keine Standortinformationen
    - Allgemeine Aussagen ohne Adressbezug
    - Aussage dass Standort unbekannt ist

    Weiß der User seine Adresse oder nicht?
    - Nur "Nein" wenn der User explizit sagt dass er seine Adresse nicht kennt.
    - Ansonsten "Ja".

    Regeln für Adress-Extraktion:
    1. Extrahiere so vollständig wie möglich.
    2. Erfinde keine zusätzlichen Details.
    3. Convertiere ausgeschriebene Zahlen in Ziffern (z.B. "einundfünfzig" -> "51").
    4. Gib die Adresse in einfacher Form zurück, z.B. "Güterstraße 12 in 94469 Deggendorf".

    Beispiele:
    Hauptstraße 5 in Immenstadt: Ja -> Ja -> -> Ja -> Hauptstraße 5 in Immenstadt
    4040 Linz: Ja -> Ja -> -> Ja -> 4040 Linz
    Ich wohne in der Friedrichstraße 5: Ja -> Nein -> Ja -> Friedrichstraße 5
    Ich weiß nicht wo ich bin.: Nein -> Nein -> Nein ->

    Orte die oft vorkommen:
    Immenstadt, Kempten, Memmingen, Allgäu region

    SONDERREGEL:
    !! Wenn der user nach einem echten Menschen, Mitarbeiter oder Agent fragt, gebe einfach "MITARBEITER" zurück und ignoriere die Standortfrage komplett, auch wenn Standortinformationen gegeben sind. !!
    """

    def parse(response: str) -> dict:
        parts = _parse_arrow_response(response, maxsplit=3)
        if len(parts) == 4:
            decision, city, knows, address_str = parts
        else:
            decision, city, knows, address_str = "Nein", "Nein", "Nein", ""
        contains_loc = decision.lower() == "ja"
        return {
            "contains_loc": contains_loc,
            "contains_city": city.lower() == "ja",
            "knows_location": knows.lower() == "ja",
            "address": address_str if contains_loc and address_str else None,
        }

    return await _cached_llm_request(
        cache_key="process_location",
        cache_input={"spoken_text": spoken_text},
        system_prompt=system_prompt,
        user_prompt=f'Text: "{spoken_text}"',
        parse_fn=parse,
        build_return=lambda d, dur, src: (d["contains_loc"], d["contains_city"], d["knows_location"], d["address"], dur, src),
        error_return=lambda _: (False, False, None, None, 0.0, "unknown"),
    )


async def correct_plz(location: str, lat: float, lon: float) -> str | None:
    """Resolve the correct postal code for an ambiguous location.

    Uses Grok with web search to disambiguate the place name based on
    the provided GPS coordinates.

    Args:
        location: Place name that may be ambiguous (e.g. "Linz").
        lat: Latitude of the caller's location.
        lon: Longitude of the caller's location.

    Returns:
        A 4-or-5-digit postal code string, or ``None`` on failure/timeout.
    """
    if not location:
        return None

    system_prompt = """
Du bist ein Experte für Postleitzahlen in Deutschland, Österreich und der Schweiz.

Gegeben ist ein Ortsname und GPS-Koordinaten. Deine Aufgabe:
1. Prüfe, ob der Ortsname mehrdeutig ist (z.B. "Linz" gibt es in AT und DE, "Neustadt" gibt es viele).
2. Falls mehrdeutig, bestimme anhand der Koordinaten, welcher Ort gemeint ist.
3. Gib die korrekte Postleitzahl zurück.
4. Nutze internet suche

Ausgabeformat (NUR eine Zeile, keine Erklärung):
- Falls mehrdeutig und Koordinaten helfen: Die korrekte PLZ (z.B. "4020")
- Gebe immer die PLZ egal ob eindeutig oder nicht: München -> 80331

Beispiele:
- Linz mit Koordinaten nahe Österreich (48.3, 14.3) -> 4020
- Linz mit Koordinaten nahe Deutschland (50.5, 7.3) -> 53545
- München (eindeutig) -> 80331
"""

    try:
        response = await asyncio.wait_for(
            _ask_grok(system_prompt, f'Koordinaten: ({lat}, {lon}), Welche PLZ ist das?', use_web_search=True),
            timeout=5.0
        )
        response = response.strip()
        if response.isdigit() and 4 <= len(response) <= 5:
            logger.info("Corrected PLZ for '%s' to '%s'", location, response)
            return response
        return None
    except asyncio.TimeoutError:
        logger.warning("correct_plz timed out for '%s'", location)
        return None
    except Exception as e:
        logger.error("Error in correct_plz: %s", e)
        return None
