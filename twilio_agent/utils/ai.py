import hashlib
import json
import logging
import os
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import cProfile
import pstats
import io
import asyncio

import dotenv
from openai import OpenAI
from xai_sdk import Client
from xai_sdk.chat import system, user
from concurrent.futures import TimeoutError

# logger = logging.getLogger("uvicorn")
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

dotenv.load_dotenv()

# --- Initialize XAI Client (Grok) ---
client = Client(api_key=os.environ["XAI_API_KEY"])

# --- Initialize Baseten Client (GPT-OSS-120B) ---
baseten_client = OpenAI(
    api_key=os.environ.get("BASETEN_API_KEY", ""),
    base_url="https://inference.baseten.co/v1",
)

# --- Cache System Setup ---
# Prefer absolute path inside container; fallback handled in _get_cache_dir
CACHE_BASE_DIR = Path("/app/ai_cache") if os.path.isabs("/app/ai_cache") else Path("./ai_cache")


def _get_cache_dir(function_name: str) -> Path:
    """Get or create cache directory for a specific function, with fallback.

    If creating the directory under CACHE_BASE_DIR is not permitted, fall back to
    using /tmp which should always be writable inside the container.
    """
    step_start = time.perf_counter()
    primary_dir = CACHE_BASE_DIR / function_name
    try:
        primary_dir.mkdir(parents=True, exist_ok=True)
        duration = time.perf_counter() - step_start
        logger.info(f"Step '_get_cache_dir' completed in {duration:.3f}s")
        return primary_dir
    except PermissionError as e:
        logger.warning(
            f"Permission denied for cache dir '{primary_dir}'. Falling back to /tmp. Error: {e}"
        )
    except Exception as e:
        logger.warning(
            f"Error creating cache dir '{primary_dir}'. Falling back to /tmp. Error: {e}"
        )

    fallback_base = Path("/tmp/ai_cache")
    fallback_dir = fallback_base / function_name
    try:
        fallback_dir.mkdir(parents=True, exist_ok=True)
        duration = time.perf_counter() - step_start
        logger.info(f"Step '_get_cache_dir' (fallback) completed in {duration:.3f}s")
        return fallback_dir
    except Exception as e:
        # As a last resort, return the primary path (calls will likely fail, but we log it)
        logger.error(
            f"Failed to create fallback cache dir '{fallback_dir}'. Continuing with primary path which may fail. Error: {e}"
        )
        duration = time.perf_counter() - step_start
        logger.info(f"Step '_get_cache_dir' (error fallback) completed in {duration:.3f}s")
        return primary_dir


def _get_cache_key(input_data: dict) -> str:
    """Generate a cache key from input data by sanitizing all text values."""
    step_start = time.perf_counter()
    # Collect all text values from the input data
    text_values = []
    for key in sorted(input_data.keys()):  # Sort for consistency
        value = input_data[key]
        if isinstance(value, str) and value.strip():  # Only non-empty strings
            text_values.append(value)

    if not text_values:
        # Fallback to hash if no text found
        data_str = json.dumps(input_data, sort_keys=True, ensure_ascii=False)
        key = hashlib.sha256(data_str.encode()).hexdigest()
        duration = time.perf_counter() - step_start
        logger.info(f"Step '_get_cache_key' (hash fallback) completed in {duration:.3f}s")
        return key

    # Combine all text values with a separator
    combined_text = " | ".join(text_values)

    # Normalize unicode and remove accents/umlauts (optimized: use str.translate for faster removal)
    normalized = unicodedata.normalize("NFD", combined_text)
    trans_table = dict.fromkeys(c for c in range(128) if unicodedata.category(chr(c)) == "Mn")
    without_accents = normalized.translate(trans_table)

    # Replace spaces with underscores and remove all punctuation (optimized: combine regex)
    sanitized = re.sub(r"[^a-zA-Z0-9_ ]", "", without_accents)  # Remove punctuation (note: space instead of \s for speed)
    sanitized = re.sub(r" +", "_", sanitized)  # Replace spaces with underscores
    sanitized = re.sub(r"_+", "_", sanitized)  # Replace multiple underscores with single
    sanitized = sanitized.strip("_").lower()  # Remove leading/trailing underscores and lowercase

    duration = time.perf_counter() - step_start
    logger.info(f"Step '_get_cache_key' completed in {duration:.3f}s")
    return sanitized


def _get_cache(function_name: str, input_data: dict) -> dict | None:
    """Retrieve cached result if it exists."""
    step_start = time.perf_counter()
    cache_dir = _get_cache_dir(function_name)
    cache_key = _get_cache_key(input_data)
    cache_file = cache_dir / f"{cache_key}.json"

    try:
        if cache_file.exists():
            logger.info(f"Hit cache for {function_name} with key {cache_key}")
            with open(cache_file, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
                logger.debug(f"Cache hit for {function_name} with key {cache_key}")
                duration = time.perf_counter() - step_start
                logger.info(f"Step '_get_cache' (hit) completed in {duration:.3f}s")
                return cached_data
    except Exception as e:
        logger.warning(f"Error reading cache for {function_name}: {e}")

    duration = time.perf_counter() - step_start
    logger.info(f"Step '_get_cache' (miss) completed in {duration:.3f}s")
    return None


def _set_cache(function_name: str, input_data: dict, result: dict) -> None:
    """Store result in cache."""
    step_start = time.perf_counter()
    cache_dir = _get_cache_dir(function_name)
    cache_key = _get_cache_key(input_data)
    cache_file = cache_dir / f"{cache_key}.json"

    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
            logger.debug(f"Cache stored for {function_name} with key {cache_key}")
        duration = time.perf_counter() - step_start
        logger.info(f"Step '_set_cache' completed in {duration:.3f}s")
    except Exception as e:
        logger.warning(f"Error writing cache for {function_name}: {e}")
        duration = time.perf_counter() - step_start
        logger.info(f"Step '_set_cache' (error) completed in {duration:.3f}s")


def _ask_grok(system_prompt: str, user_prompt: str) -> str:
    """Shared function for Grok API calls."""
    step_start = time.perf_counter()
    if client is None:
        logger.error("Client not initialized. Returning empty response.")
        duration = time.perf_counter() - step_start
        logger.info(f"Step '_ask_grok' (uninitialized) completed in {duration:.3f}s")
        return ""
    try:
        chat = client.chat.create(model="grok-4-fast-non-reasoning", temperature=0)
        chat.append(system(system_prompt))
        chat.append(user(user_prompt))
        response_grok = chat.sample()
        duration = time.perf_counter() - step_start
        logger.info(f"Step '_ask_grok' completed in {duration:.3f}s")
        return response_grok.content.strip()
    except Exception as e:
        logger.error(f"Grok API call failed: {e}")
        duration = time.perf_counter() - step_start
        logger.info(f"Step '_ask_grok' (error) completed in {duration:.3f}s")
        return ""


def _ask_baseten(system_prompt: str, user_prompt: str) -> str:
    """Make a request to GPT-OSS-120B via Baseten."""
    step_start = time.perf_counter()
    if not baseten_client or not os.environ.get("BASETEN_API_KEY"):
        logger.debug("Baseten client not configured.")
        duration = time.perf_counter() - step_start
        logger.info(f"Step '_ask_baseten' (unconfigured) completed in {duration:.3f}s")
        return ""
    try:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        response = baseten_client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=messages,
            temperature=0,
            max_tokens=1000,
            top_p=1,
            presence_penalty=0,
            frequency_penalty=0,
        )
        if response.choices and response.choices[0].message:
            duration = time.perf_counter() - step_start
            logger.info(f"Step '_ask_baseten' completed in {duration:.3f}s")
            return response.choices[0].message.content.strip()
        duration = time.perf_counter() - step_start
        logger.info(f"Step '_ask_baseten' (no response) completed in {duration:.3f}s")
        return ""
    except Exception as e:
        logger.debug(f"Baseten API call failed: {e}")
        duration = time.perf_counter() - step_start
        logger.info(f"Step '_ask_baseten' (error) completed in {duration:.3f}s")
        return ""


async def _ask_llm_parallel(system_prompt: str, user_prompt: str) -> tuple[str, str]:
    """
    Request both Grok and Baseten LLMs in parallel.
    Returns (response, model_source) where model_source is "grok" or "gpt".
    Uses Grok if it completes within 1 second.
    Otherwise, uses whichever completes first.
    Falls back to the other if one fails.
    """

    start_time = time.time()

    grok_task = asyncio.create_task(_ask_grok(system_prompt, user_prompt))
    baseten_task = asyncio.create_task(_ask_baseten(system_prompt, user_prompt))

    try:
        # Wait up to 1s for grok_task only
        done, pending = await asyncio.wait([grok_task], timeout=1)
        if done:
            grok_result = await grok_task
            elapsed = time.time() - start_time
            # cancel Baseten, since Grok succeeded in time
            baseten_task.cancel()
            try:
                await baseten_task
            except asyncio.CancelledError:
                pass
            return grok_result, "grok" if grok_result else ("", "unknown")
        else:
            # Grok didn't finish in 1s, now race both
            done_both, pending_both = await asyncio.wait([grok_task, baseten_task], return_when=asyncio.FIRST_COMPLETED)
            finished_task = done_both.pop()
            resp = await finished_task
            model_source = "grok" if finished_task == grok_task else "gpt"
            # Cancel the other still running task
            for task in pending_both:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            return resp, model_source if resp else ("", "unknown")
    except Exception:
        return "", "unknown"
    finally:
        for task in [grok_task, baseten_task]:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass


def classify_intent(spoken_text: str) -> tuple[str, str, float, str]:
    """
    Classifies the user's intent into a predefined set of categories.
    Returns (classification, reasoning, duration, model_source)
    """
    start_time = time.time()
    step_start = time.perf_counter()
    choices = ["schlüsseldienst", "abschleppdienst", "adac", "mitarbeiter", "andere"]
    fallback = "andere"

    if not spoken_text:
        duration = time.perf_counter() - step_start
        logger.info(f"Step 'classify_intent' (empty text) completed in {duration:.3f}s")
        return fallback, "Kein Text vorhanden.", -1.0, "cache"

    # Check cache first
    cache_input = {"spoken_text": spoken_text}
    cached_result = _get_cache("classify_intent", cache_input)
    if cached_result:
        logger.info(f"Returning cached result for classify_intent")
        duration = time.perf_counter() - step_start
        logger.info(f"Step 'classify_intent' (cache hit) completed in {duration:.3f}s")
        return cached_result["classification"], cached_result["reasoning"], 0.0, "cache"

    try:
        choices_str = "', '".join(choices)
        system_prompt = f"""
    Du klassifizierst exakt in eine dieser Klassen: '{choices_str}'. Gib die Klassifizierung und eine kurze Begründung auf Deutsch aus.

    FORMAT: <Begründung> -> <Klasse>

    Wähle EINE der folgenden Klassen: {choices_str} 
    Gebe die klasse und begründung ohne < und > aus. Nutze immmer ->.

    Begründung kurz auf Deutsch. Nenne wenn möglich die Regel. max 10 wörter.

    REGELN (kurz & strikt):
    1. abschleppdienst:
       1.1 Alle KFZ-/Pannen-/Fahrzeugprobleme.
       1.2 Varianten: Motor/Mordor, Wagen/WAAGE, Batterie leer, Reifen/Reif kaputt, kein Benzin, ab schleppen, abschleppen, Panne/Pfanne, Rauch, brennt.
       1.3 Eingeschlossener Autoschlüssel (Schlüssel im Auto, Schüssel im Auto, steckt im Auto) => abschleppdienst.
    2. schlüsseldienst:
       2.1 Haus / Wohnung / Tür (Tür/Tour), Schloss zu.
       2.2 Schlüssel (Schlüssel/Schüssel) verloren/abgebrochen/steckt von innen im Auto.
       2.3 Alles rund ums Auto wenn der Schlüssel betroffen ist.
       2.4 "Türen sind zu" ohne klaren Auto-Kontext => schlüsseldienst.
    3. adac:
       3.1 Erwähnungen/Varianten: adac, a d a c, a d c, ad hoc dienst (falls offensichtlich gemeint), der ac? => adac.
    4. mitarbeiter:
       4.1 Wunsch nach Mensch / Mitarbeiter / Arbeiter / Agent / realer Person / durchstellen / verbinden / sprechen mit jemand / menschlicher Ansprechpartner.
       4.2 Auch verschrieben (mit Arbeiter, Arbeiter).
       4.3 Aussagen wie "Kann ich mit jemandem über mein Auto reden?" => mitarbeiter.
       4.4 Privates Anliegen => mitarbeiter.
    5. andere:
       5.1 Alles Administrative (Kündigung, Kostenfrage).
       5.2 Unklare generische Hilfe ("Brauche Hilfe").
       5.3 Irrelevantes oder zu vages ohne klare Zuordnung.

    PRIORITÄTEN BEI AMBIGUITÄT:
    1. Wenn sowohl Schlüssel- als-auch Auto-Kontext: Entscheide immer für schlüsseldienst.
    2. Enthält klaren Wunsch nach Mensch (sprechen, verbinden) überschreibt andere Hinweise => mitarbeiter.
    3. Sonst fallback '{fallback}'.

    Beispiele
    - "Ich habe meinen Autoschlüssel verloren" => "Schlüssel verloren, Auto betroffen. -> schlüsseldienst"
    - "Mein Auto springt nicht an" => "Auto startet nicht. -> abschleppdienst"

    """
        user_prompt = f'Kategorisiere diese Anfrage: "{spoken_text}"'

        response, model_source = _ask_llm_parallel(system_prompt, user_prompt)
        response = response.strip()
        if "->" in response:
            reasoning, classification = response.split("->", 1)
            classification = classification.strip().lower()
            reasoning = reasoning.strip()
        else:
            classification = response.lower()
            reasoning = "Keine Begründung gegeben."

        result = classification if classification in choices else fallback
        if result != classification:
            reasoning = f"Unerwartete Klassifizierung '{classification}', fallback zu '{result}'. Ursprüngliche Begründung: {reasoning}"

        duration_total = time.time() - start_time
        logger.info(f"Classification completed in {duration_total:.3f}s. Result: {result}. Model: {model_source}")

        # Cache the result
        _set_cache(
            "classify_intent",
            cache_input,
            {"classification": result, "reasoning": reasoning},
        )

        duration = time.perf_counter() - step_start
        logger.info(f"Step 'classify_intent' completed in {duration:.3f}s")
        return result, reasoning, duration_total, model_source

    except Exception as e:
        duration_total = time.time() - start_time
        logger.error(f"Error in classify_intent after {duration_total:.3f}s: {e}")
        duration = time.perf_counter() - step_start
        logger.info(f"Step 'classify_intent' (error) completed in {duration:.3f}s")
        return fallback, f"Fehler: {e}", duration_total, "unknown"


def yes_no_question(spoken_text: str, context: str) -> tuple[bool, str, float, str]:
    """
    Determines if spoken text represents clear agreement (Yes) or not (No).
    Returns (is_agreement, reasoning, duration, model_source)
    """
    start_time = time.time()
    step_start = time.perf_counter()
    if not spoken_text:
        duration = time.perf_counter() - step_start
        logger.info(f"Step 'yes_no_question' (empty text) completed in {duration:.3f}s")
        return False, "Kein Text vorhanden.", 0.0, "cache"

    # Check cache first
    cache_input = {"spoken_text": spoken_text, "context": context}
    cached_result = _get_cache("yes_no_question", cache_input)
    if cached_result:
        logger.info(f"Returning cached result for yes_no_question")
        duration = time.perf_counter() - step_start
        logger.info(f"Step 'yes_no_question' (cache hit) completed in {duration:.3f}s")
        return cached_result["is_agreement"], cached_result["reasoning"], 0.0, "cache"

    try:
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
    """
        user_prompt = f'Kontext: "{context}" \nAntwort des Benutzers: "{spoken_text}". Zeigt dies eine bejahende Absicht?'

        response, model_source = _ask_llm_parallel(system_prompt, user_prompt)
        response = response.strip()
        if "->" in response:
            reasoning, decision = response.split("->", 1)
            decision = decision.strip()
            reasoning = reasoning.strip()
        else:
            decision = response
            reasoning = "Keine Begründung gegeben."

        is_agreement = decision == "Ja"
        duration_total = time.time() - start_time

        logger.info(
            f"Yes/No question completed in {duration_total:.3f}s. Result: {is_agreement}. Model: {model_source}"
        )

        # Cache the result
        _set_cache(
            "yes_no_question",
            cache_input,
            {"is_agreement": is_agreement, "reasoning": reasoning},
        )

        duration = time.perf_counter() - step_start
        logger.info(f"Step 'yes_no_question' completed in {duration:.3f}s")
        return is_agreement, reasoning, duration_total, model_source

    except Exception as e:
        duration_total = time.time() - start_time
        logger.error(f"Error in yes_no_question after {duration_total:.3f}s: {e}")
        duration = time.perf_counter() - step_start
        logger.info(f"Step 'yes_no_question' (error) completed in {duration:.3f}s")
        return False, f"Fehler: {e}", duration_total, "unknown"


def contains_location(spoken_text: str) -> tuple[bool, str, float, str]:
    """
    Determines if spoken text contains any kind of location information.
    Returns (contains_location, reasoning, duration, model_source)
    """
    start_time = time.time()
    step_start = time.perf_counter()
    if not spoken_text:
        duration = time.perf_counter() - step_start
        logger.info(f"Step 'contains_location' (empty text) completed in {duration:.3f}s")
        return False, "Kein Text vorhanden.", 0.0, "cache"

    # Check cache first
    cache_input = {"spoken_text": spoken_text}
    cached_result = _get_cache("contains_location", cache_input)
    if cached_result:
        logger.info(f"Returning cached result for contains_location")
        duration = time.perf_counter() - step_start
        logger.info(f"Step 'contains_location' (cache hit) completed in {duration:.3f}s")
        return cached_result["contains_loc"], cached_result["reasoning"], 0.0, "cache"

    try:
        system_prompt = """
    Entscheide, ob der gegebene Text Standortinformationen enthält. Gib eine kurze Begründung (max 10 Wörter) und "Ja" oder "Nein" auf Deutsch aus.

    Format: <Begründung> -> <Ja/Nein>
    Immer -> verwenden. Ohne < >.

    Ja bei jeglichen Standortinformationen, inkl.:
    - Straßenname, Hausnummer
    - Postleitzahl, Ortsname
    - Autobahnnummern mit Ortsangaben
    - Teiladressen oder nur Ortsnamen

    Nein bei:
    - Keine Standortinformationen
    - Allgemeine Aussagen ohne Adressbezug
    - Aussage dass Standort unbekannt ist

    Beispiele:
    - "Ich wohne in der Güterstraße 12 in 94469 Deggendorf." => "Enthält Adresse. -> Ja"
    - "Kannst du zu mir kommen? Ich bin krank." => "Keine Adresse. -> Nein"
    """
        user_prompt = f'Text: "{spoken_text}"'

        response, model_source = _ask_llm_parallel(system_prompt, user_prompt)
        response = response.strip()
        if "->" in response:
            reasoning, decision = response.split("->", 1)
            decision = decision.strip()
            reasoning = reasoning.strip()
        else:
            decision = response
            reasoning = "Keine Begründung gegeben."

        contains_loc = decision == "Ja"
        duration_total = time.time() - start_time

        logger.info(
            f"Location presence check completed in {duration_total:.3f}s. Result: {contains_loc}. Model: {model_source}"
        )

        # Cache the result
        _set_cache(
            "contains_location",
            cache_input,
            {"contains_loc": contains_loc, "reasoning": reasoning},
        )

        duration = time.perf_counter() - step_start
        logger.info(f"Step 'contains_location' completed in {duration:.3f}s")
        return contains_loc, reasoning, duration_total, model_source

    except Exception as e:
        duration_total = time.time() - start_time
        logger.error(f"Error in contains_location after {duration_total:.3f}s: {e}")
        duration = time.perf_counter() - step_start
        logger.info(f"Step 'contains_location' (error) completed in {duration:.3f}s")
        return False, f"Fehler: {e}", duration_total, "unknown"


def extract_location(spoken_text: str) -> tuple[str, str, float, str]:
    """
    Extracts only the address part from spoken text.
    Returns (address, reasoning, duration, model_source)
    """
    start_time = time.time()
    step_start = time.perf_counter()

    # Check cache first
    cache_input = {"spoken_text": spoken_text}
    cached_result = _get_cache("extract_location", cache_input)
    if cached_result:
        logger.info(f"Returning cached result for extract_location")
        duration = time.perf_counter() - step_start
        logger.info(f"Step 'extract_location' (cache hit) completed in {duration:.3f}s")
        return cached_result["address"], cached_result["reasoning"], 0.0, "cache"

    try:
        system_prompt = """
    Extrahiere NUR den Adressteil aus dem gesprochenen Text. Gib die Adresse und eine kurze Begründung auf Deutsch aus.

    Gebe nur die Adresse zurück, ohne zusätzliche Erklärungen. Keine Begründung oder Kontext. Nur die Adresse.

    REGELN:
    - Behalte: Straßenname, Hausnummer, PLZ, Ortsname
    - Entferne: Füllwörter, Fragen, Zeitangaben, persönliche Kommentare
    - Format: "Straße Hausnummer in PLZ Ort" oder verfügbare Teile davon
    - Falls keine Adresse erkennbar: "Keine Adresse"

    BEISPIELE:
    "Ich wohne in der Güterstraße 12 in 94469 Deggendorf." => "Güterstraße 12 in 94469 Deggendorf"
    "Meine Adresse ist Hauptstraße 5, 80331 München." => "Hauptstraße 5, 80331 München"
    "Kannst du zu mir kommen? Ich bin krank." => "Keine Adresse"
    "7 9 5 9 2" => "79592"
    "Osterhofen" => "Osterhofen"
    "Ich bin auf der A96 bei Plattling." => "A96 bei Plattling"
    """
        user_prompt = f'Text: "{spoken_text}"'

        response, model_source = _ask_llm_parallel(system_prompt, user_prompt)
        response = response.strip()
        address = response if response and response != "Keine Adresse" else None
        duration_total = time.time() - start_time

        logger.info(f"Location extraction completed in {duration_total:.3f}s. Model: {model_source}")

        # Cache the result
        _set_cache(
            "extract_location",
            cache_input,
            {"address": address, "reasoning": "Extraktion abgeschlossen."},
        )

        duration = time.perf_counter() - step_start
        logger.info(f"Step 'extract_location' completed in {duration:.3f}s")
        return address, "Extraktion abgeschlossen.", duration_total, model_source
    except Exception as e:
        duration_total = time.time() - start_time
        logger.error(f"Error in extract_location after {duration_total:.3f}s: {e}")
        duration = time.perf_counter() - step_start
        logger.info(f"Step 'extract_location' (error) completed in {duration:.3f}s")
        return None, f"Fehler: {e}", duration_total, "unknown"


def profile_function(func, *args, **kwargs):
    """Profile a function call using cProfile and log the stats."""
    pr = cProfile.Profile()
    pr.enable()
    result = func(*args, **kwargs)
    pr.disable()
    s = io.StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats('cumulative')
    ps.print_stats(20)  # Print top 20 lines
    logger.info(f"Profiling stats for {func.__name__}:\n{s.getvalue()}")
    return result


if __name__ == "__main__":
    # Test cases for classify_intent
    test_cases_classify = [
        "Mein Auto springt nicht an.",
        "Ich habe meinen Schlüssel verloren.",
        "Ich brauche Hilfe vom ADAC.",
        "Kann ich mit einem Mitarbeiter sprechen?",
        "Ich möchte meine Mitgliedschaft kündigen.",
        "Mein Schlüssel steckt im Auto.",
        "Mein Reifen ist kaputt.",
        "Ich bin eingeschlossen in meinem Haus.",
        "Ich brauche Hilfe mit meinem Fahrzeug.",
        "Ich möchte einen Termin vereinbaren.",
    ]

    print("Testing classify_intent:")
    for i, text in enumerate(test_cases_classify, 1):
        result, reasoning, duration, model_source = profile_function(classify_intent, text)
        print(
            f"Case {i}: '{text}' -> {result} (Reason: {reasoning}, Time: {duration:.3f}s) {model_source}"
        )

    # Test cases for yes_no_question
    test_cases_yes_no = [
        ("Ja, gerne.", "Möchten Sie Hilfe?"),
        ("Nein, danke.", "Ist das korrekt?"),
        ("Genau.", "Bestätigen Sie?"),
        ("Ich weiß nicht.", "Sind Sie sicher?"),
        ("Stimmt.", "Passt das?"),
        ("Nicht richtig.", "Ist das so?"),
        ("Alles klar.", "Einverstanden?"),
        ("Bitte wiederholen.", "Verstehen Sie?"),
        ("Na gut.", "Okay?"),
        ("Ganz und gar nicht.", "Richtig?"),
    ]

    print("\nTesting yes_no_question:")
    for i, (text, context) in enumerate(test_cases_yes_no, 1):
        is_agreement, reasoning, duration, model_source = profile_function(yes_no_question, text, context)
        print(
            f"Case {i}: '{text}' in '{context}' -> {is_agreement} (Reason: {reasoning}, Time: {duration:.3f}s) {model_source}"
        )

    # Test cases for extract_location
    test_cases_extract = [
        "Ich wohne in der Güterstraße 12 in 94469 Deggendorf.",
        "Meine Adresse ist Hauptstraße 5, 80331 München.",
        "Kannst du zu mir kommen? Ich bin krank.",
        "7 9 5 9 2",
        "Osterhofen",
        "Ich bin auf der A3 bei Plattling.",
        "Ich bin in der Stadtgasse 10 in München.",
        "Adresse: Berliner Straße 42, 10117 Berlin.",
        "Keine Adresse hier.",
        "In der Nähe von Passau, Straße unbekannt.",
    ]

    print("\nTesting extract_location:")
    for i, text in enumerate(test_cases_extract, 1):
        address, reasoning, duration, model_source = profile_function(extract_location, text)
        print(
            f"Case {i}: '{text}' -> '{address}' (Reason: {reasoning}, Time: {duration:.3f}s) {model_source}"
        )

    test_cases_contains_location = [
        "Ich wohne in der Güterstraße 12 in 94469 Deggendorf.",
        "Kannst du zu mir kommen? Ich bin krank.",
        "7 9 5 9 2",
        "Osterhofen",
        "Ich bin auf der A3 bei Plattling.",
        "Keine Adresse hier.",
        "In der Nähe von Passau, Straße unbekannt.",
        "Treffen wir uns im Park.",
        "Meine Wohnung ist in der Innenstadt.",
        "Ich habe keine Ahnung, wo ich bin.",
    ]

    print("\nTesting contains_location:")
    for i, text in enumerate(test_cases_contains_location, 1):
        has_location, reasoning, duration, model_source = profile_function(contains_location, text)
        print(
            f"Case {i}: '{text}' -> {has_location} (Reason: {reasoning}, Time: {duration:.3f}s) {model_source}"
        )