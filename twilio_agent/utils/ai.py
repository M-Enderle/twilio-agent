import asyncio
import logging
import os
import time

import dotenv
from openai import OpenAI
from xai_sdk import Client
from xai_sdk.chat import system, user

from twilio_agent.utils.cache import CacheManager

# logger = logging.getLogger("uvicorn")
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

dotenv.load_dotenv()

# --- Initialize XAI Client (Grok) ---
client = Client(api_key=os.environ["XAI_API_KEY"])

# --- Initialize Baseten Client (GPT-OSS-120B) ---
baseten_client = OpenAI(
    api_key=os.environ.get("BASETEN_API_KEY", ""),
    base_url="https://inference.baseten.co/v1",
)

cache_manager = CacheManager("LLM")


async def _ask_grok(system_prompt: str, user_prompt: str) -> str:
    """Shared function for Grok API calls.

    The underlying SDK is synchronous, so run it in a thread via
    asyncio.to_thread to make this an awaitable coroutine.
    """
    if client is None:
        logger.error("Client not initialized. Returning empty response.")
        return ""

    def _sync_call():
        try:
            chat = client.chat.create(model="grok-4-fast-non-reasoning", temperature=0)
            chat.append(system(system_prompt))
            chat.append(user(user_prompt))
            response_grok = chat.sample()
            return response_grok.content.strip()
        except Exception as e:
            logger.error(f"Grok API call failed: {e}")
            return ""

    return await asyncio.to_thread(_sync_call)


async def _ask_baseten(system_prompt: str, user_prompt: str) -> str:
    """Make a request to GPT-OSS-120B via Baseten.

    The Baseten client is synchronous; run it in a thread to be awaitable.
    """
    if not baseten_client or not os.environ.get("BASETEN_API_KEY"):
        logger.debug("Baseten client not configured.")
        return ""

    def _sync_call():
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
                return response.choices[0].message.content.strip()
            return ""
        except Exception as e:
            logger.debug(f"Baseten API call failed: {e}")
            return ""

    return await asyncio.to_thread(_sync_call)


async def _ask_llm_parallel(system_prompt: str, user_prompt: str) -> tuple[str, str]:
    """
    Request both Grok and Baseten LLMs in parallel.
    Returns (response, model_source) where model_source is "grok" or "gpt".
    Uses Grok if it completes within 1 second.
    Otherwise, uses whichever completes first.
    Falls back to the other if one fails.
    """

    grok_task = asyncio.create_task(_ask_grok(system_prompt, user_prompt))
    baseten_task = asyncio.create_task(_ask_baseten(system_prompt, user_prompt))

    try:
        # Wait up to 1s for grok_task only
        done, pending = await asyncio.wait([grok_task], timeout=1)
        if done:
            grok_result = await grok_task
            # cancel Baseten, since Grok succeeded in time
            baseten_task.cancel()
            try:
                await baseten_task
            except asyncio.CancelledError:
                pass
            return (grok_result, "grok") if grok_result else ("", "unknown")
        else:
            # Grok didn't finish in 1s, now race both
            done_both, pending_both = await asyncio.wait(
                [grok_task, baseten_task], return_when=asyncio.FIRST_COMPLETED
            )
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
            return (resp, model_source) if resp else ("", "unknown")
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


async def classify_intent(spoken_text: str) -> tuple[str, str, float | None, str]:
    """
    Classifies the user's intent into a predefined set of categories.
    Returns (classification, reasoning, duration, model_source) where duration is None when timing data is unavailable.
    """
    choices = ["schlüsseldienst", "abschleppdienst", "adac", "mitarbeiter", "andere"]
    fallback = "andere"

    if not spoken_text:
        return fallback, "Kein Text vorhanden.", None, "cache"

    # Check cache first
    cache_input = {"spoken_text": spoken_text}
    cached_result = cache_manager.get("classify_intent", cache_input)
    if cached_result:
        logger.info(f"Returning cached result for classify_intent")
        return (
            cached_result.get("classification"),
            cached_result.get("reasoning"),
            0.0,
            "cache",
        )

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

        start = time.monotonic()
        response, model_source = await _ask_llm_parallel(system_prompt, user_prompt)
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

        logger.info(f"Classification result: {result}. Model: {model_source}")

        duration = time.monotonic() - start
        # Cache the result (include duration)
        cache_manager.set(
            "classify_intent",
            cache_input,
            {"classification": result, "reasoning": reasoning, "duration": duration},
        )

        return result, reasoning, duration, model_source

    except Exception as e:
        logger.error(f"Error in classify_intent: {e}")
        return fallback, f"Fehler: {e}", None, "unknown"


async def yes_no_question(
    spoken_text: str, context: str
) -> tuple[bool, str, float | None, str]:
    """
    Determines if spoken text represents clear agreement (Yes) or not (No).
    Returns (is_agreement, reasoning, duration, model_source) where duration is None when timing data is unavailable.
    """
    if not spoken_text:
        return False, "Kein Text vorhanden.", None, "cache"

    # Check cache first
    cache_input = {"spoken_text": spoken_text, "context": context}
    cached_result = cache_manager.get("yes_no_question", cache_input)
    if cached_result:
        logger.info(f"Returning cached result for yes_no_question")
        return (
            cached_result.get("is_agreement"),
            cached_result.get("reasoning"),
            0.0,
            "cache",
        )

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

        start = time.monotonic()
        response, model_source = await _ask_llm_parallel(system_prompt, user_prompt)
        response = response.strip()
        if "->" in response:
            reasoning, decision = response.split("->", 1)
            decision = decision.strip()
            reasoning = reasoning.strip()
        else:
            decision = response
            reasoning = "Keine Begründung gegeben."

        is_agreement = decision == "Ja"
        logger.info(f"Yes/No question result: {is_agreement}. Model: {model_source}")

        duration = time.monotonic() - start
        # Cache the result including duration
        cache_manager.set(
            "yes_no_question",
            cache_input,
            {
                "is_agreement": is_agreement,
                "reasoning": reasoning,
                "duration": duration,
            },
        )

        return is_agreement, reasoning, duration, model_source

    except Exception as e:
        logger.error(f"Error in yes_no_question: {e}")
        return False, f"Fehler: {e}", None, "unknown"


async def process_location(
    spoken_text: str,
) -> tuple[bool, bool, str | None, float | None, str]:
    """
    Determines if spoken text contains location information and extracts it if present.
    Returns (contains_location, extracted_address, reasoning, duration, model_source).
    Note: Do not return any reasoning from the model; reasoning is always an empty string.
    """
    if not spoken_text:
        return None, None, None, None, 0.0, "cache"

    # Check cache first
    cache_input = {"spoken_text": spoken_text}
    cached_result = cache_manager.get("process_location", cache_input)
    if cached_result:
        logger.info(f"Returning cached result for process_location")
        return (
            cached_result.get("contains_loc"),
            cached_result.get("contains_city"),
            cache_input.get("knows_location"),
            cached_result.get("address"),
            0.0,
            "cache",
        )

    try:
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
    """
        user_prompt = f'Text: "{spoken_text}"'

        start = time.monotonic()
        response, model_source = await _ask_llm_parallel(system_prompt, user_prompt)
        response = response.strip()

        parts = [p.strip() for p in response.split("->", 3)]
        if len(parts) == 4:
            decision = parts[0]
            contains_city = parts[1]
            knows_location = parts[2]
            address_str = parts[3]
        else:
            decision = "Nein"
            contains_city = "Nein"
            knows_location = "Nein"
            address_str = ""

        contains_loc = decision.lower() == "ja"
        contains_city_bool = contains_city.lower() == "ja"
        knows_location_bool = knows_location.lower() == "ja"
        extracted_address = address_str if contains_loc and address_str else None

        logger.info(
            f"Location processing result: contains={contains_loc}, contains_city={contains_city_bool}, address={extracted_address}. Model: {model_source}"
        )

        duration = time.monotonic() - start
        # Cache the result including duration (reasoning intentionally omitted)
        cache_manager.set(
            "process_location",
            cache_input,
            {
                "contains_loc": contains_loc,
                "contains_city": contains_city_bool,
                "knows_location": knows_location_bool,
                "address": extracted_address,
                "duration": duration,
            },
        )

        return (
            contains_loc,
            contains_city_bool,
            knows_location_bool,
            extracted_address,
            duration,
            model_source,
        )

    except Exception as e:
        logger.error(f"Error in process_location: {e}")
        return False, None, "", None, "unknown"


if __name__ == "__main__":

    async def main():
        text = "Johann Wilhelm Kleinstraße einundfünfzig"
        contains_loc, contains_city, address, duration, model = await process_location(
            text
        )
        print(f"Contains location: {contains_loc}")
        print(f"Contains city: {contains_city}")
        print(f"Extracted address: {address}")
        print(f"Duration: {duration}")
        print(f"Model used: {model}")

    asyncio.run(main())
