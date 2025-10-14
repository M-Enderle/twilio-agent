import logging
import os
import time

import dotenv
from xai_sdk import Client
from xai_sdk.chat import system, user

logger = logging.getLogger("uvicorn")

dotenv.load_dotenv()

# --- Initialize XAI Client ---
client = Client(api_key=os.environ["XAI_API_KEY"])


def _ask_grok(system_prompt: str, user_prompt: str) -> str:
    """Shared function for Grok API calls."""
    if client is None:
        logger.error("Client not initialized. Returning empty response.")
        return ""
    try:
        chat = client.chat.create(model="grok-4-fast-non-reasoning")
        chat.append(system(system_prompt))
        chat.append(user(user_prompt))
        response_grok = chat.sample()
        return response_grok.content.strip()
    except Exception as e:
        logger.error(f"Grok API call failed: {e}")
        return ""


def classify_intent(spoken_text: str) -> tuple[str, str, float]:
    """
    Classifies the user's intent into a predefined set of categories.
    Returns (classification, reasoning, duration)
    """
    start_time = time.time()
    choices = ["schlüsseldienst", "abschleppdienst", "adac", "mitarbeiter", "andere"]
    fallback = "andere"

    if not spoken_text:
        return fallback, "Kein Text vorhanden.", -1.0

    try:
        choices_str = "', '".join(choices)
        system_prompt = f"""
    Du klassifizierst exakt in eine dieser Klassen: '{choices_str}'. Gib die Klassifizierung und eine kurze Begründung auf Deutsch aus.

    FORMAT: <Begründung>: <Klassenname>

    Wähle EINE der folgenden Klassen: {choices_str} 
    Gebe die klasse und begründung ohne < und > aus. 

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
    5. andere:
       5.1 Alles Administrative (Kündigung, Kostenfrage).
       5.2 Unklare generische Hilfe ("Brauche Hilfe").
       5.3 Irrelevantes oder zu vages ohne klare Zuordnung.

    PRIORITÄTEN BEI AMBIGUITÄT:
    1. Wenn sowohl Schlüssel- als-auch Auto-Kontext: Entscheide immer für schlüsseldienst.
    2. Enthält klaren Wunsch nach Mensch (sprechen, verbinden) überschreibt andere Hinweise => mitarbeiter.
    3. Sonst fallback '{fallback}'.
    """
        user_prompt = f'Kategorisiere diese Anfrage: "{spoken_text}"'

        response = _ask_grok(system_prompt, user_prompt).strip()
        if ":" in response:
            reasoning, classification = response.split(":", 1)
            classification = classification.strip().lower()
            reasoning = reasoning.strip()
        else:
            classification = response.lower()
            reasoning = "Keine Begründung gegeben."

        result = classification if classification in choices else fallback
        if result != classification:
            reasoning = f"Unerwartete Klassifizierung '{classification}', fallback zu '{result}'. Ursprüngliche Begründung: {reasoning}"

        duration = time.time() - start_time
        logger.info(f"Classification completed in {duration:.3f}s. Result: {result}")
        return result, reasoning, duration

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"Error in classify_intent after {duration:.3f}s: {e}")
        return fallback, f"Fehler: {e}", duration


def yes_no_question(spoken_text: str, context: str) -> tuple[bool, str, float]:
    """
    Determines if spoken text represents clear agreement (Yes) or not (No).
    Returns (is_agreement, reasoning, duration)
    """
    start_time = time.time()
    if not spoken_text:
        return False, "Kein Text vorhanden.", 0.0

    try:
        system_prompt = """
Du entscheidest: zeigt die Antwort eine Zustimmung? Gib "Ja" oder "Nein" und eine kurze Begründung auf Deutsch aus.

FORMAT: <Begründung>: <Ja/Nein>
Gebe die antwort und begründung ohne < und > aus. Die Begründung soll kurz sein (max 10 Wörter).

JA falls klare oder schwache Zustimmung / Bestätigung, inkl.:
- Varianten & Umgangssprache: ja, jup, jo, genau / geh nau / ge nau, absolut, stimmt, stimmt so, passt, in ordnung, alles klar, na gut, na ja (ohne klaren Widerspruch), bin sicher, machen wir so.
- Eingeleitete Zustimmung mit Nachsatz: "Stimmt, aber..." => Ja.
- Verballhornte ASR-Fehler: schwimmt / das schwimmt (für "stimmt") => Ja, Jagd (für "ja") wenn Kontext zustimmend.

NEIN falls:
- Explizite Negation: nein, keineswegs, ganz und gar nicht.
- Bitte um Wiederholung / Unklarheit: "bitte wiederholen", "weiß nicht", "egal".
- Verneinende Konstruktionen: "stimmt nicht", "nicht richtig".
- Frage zurück ohne Zustimmung.

Ambig ohne positives Signal => Nein. Sonst Ja.
"""
        user_prompt = f'Kontext: "{context}" \nAntwort des Benutzers: "{spoken_text}". Zeigt dies eine bejahende Absicht?'

        response = _ask_grok(system_prompt, user_prompt).strip()
        if ":" in response:
            reasoning, decision = response.split(":", 1)
            decision = decision.strip()
            reasoning = reasoning.strip()
        else:
            decision = response
            reasoning = "Keine Begründung gegeben."

        is_agreement = decision == "Ja"
        duration = time.time() - start_time

        logger.info(
            f"Yes/No question completed in {duration:.3f}s. Result: {is_agreement}"
        )
        return is_agreement, reasoning, duration

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"Error in yes_no_question after {duration:.3f}s: {e}")
        return False, f"Fehler: {e}", duration


def extract_location(spoken_text: str) -> tuple[str, str, float]:
    """
    Extracts only the address part from spoken text.
    Returns (address, reasoning, duration)
    """
    start_time = time.time()

    try:
        system_prompt = """
Extrahiere NUR den Adressteil aus dem gesprochenen Text. Gib die Adresse und eine kurze Begründung auf Deutsch aus.

FORMAT: <Begründung>: <Adresse>
Gebe die antwort und begründung ohne < und > aus. Die Begründung soll kurz sein (max 10 Wörter).

REGELN:
- Behalte: Straßenname, Hausnummer, PLZ, Ortsname
- Entferne: Füllwörter, Fragen, Zeitangaben, persönliche Kommentare
- Format: "Straße Hausnummer in PLZ Ort" oder verfügbare Teile davon
- Falls keine Adresse erkennbar: "Keine Adresse"

BEISPIELE:
"Ich wohne in der Güterstraße 12 in 94469 Deggendorf, wann kommst du?" -> "Güterstraße 12 in 94469 Deggendorf: Adresse aus Wohnort-Erwähnung extrahiert."
"Meine Adresse ist Hauptstraße 5, 80331 München" -> "Hauptstraße 5, 80331 München: Direkte Adressangabe."
"Kannst du zu mir kommen? Ich bin krank." -> "Keine Adresse: Keine Adressinformationen vorhanden."
"7 9 5 9 2" -> "79592: Nur PLZ erkannt."
"Osterhofen" -> "Osterhofen: Nur Ortsname."
"Ich bin auf der a3 bei Plattling" -> "Plattling: Ort aus Verkehrshinweis."
"Ich bin in der Stadtgasse 10 in München" -> "Stadtgasse 10 in München: Vollständige Adresse."
"""
        user_prompt = f'Text: "{spoken_text}"'

        response = _ask_grok(system_prompt, user_prompt).strip()
        if ":" in response:
            reasoning, address = response.split(":", 1)
            address = address.strip()
            reasoning = reasoning.strip()
        else:
            address = response
            reasoning = "Keine Begründung gegeben."

        duration = time.time() - start_time
        logger.info(
            f"Location extraction completed in {duration:.3f}s. Result: {address}"
        )
        return address.strip(), reasoning, duration

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"Error extracting location after {duration:.3f}s: {e}")
        return "Keine Adresse", f"Fehler: {e}", duration
