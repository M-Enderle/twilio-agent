
import logging
import os
import time

from xai_sdk import Client
from xai_sdk.chat import system, user
import dotenv

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


def classify_intent(spoken_text: str) -> tuple[str, float]:
    """
    Classifies the user's intent into a predefined set of categories.
    """
    start_time = time.time()
    choices = ["schlüsseldienst", "abschleppdienst", "adac", "mitarbeiter", "andere"]
    fallback = "andere"

    if not spoken_text:
        return fallback, -1.0

    try:
        choices_str = "', '".join(choices)
        system_prompt = f"""
Du klassifizierst exakt in eine dieser Klassen: '{choices_str}'. Antworte NUR mit dem Klassen-Namen.

REGELN (kurz & strikt):
1. abschleppdienst: Alle KFZ-/Pannen-/Fahrzeugprobleme (Motor/Mordor, Wagen/WAAGE, Batterie leer, Reifen/Reif kaputt, kein Benzin, ab schleppen, abschleppen, Panne/Pfanne, Rauch, brennt). Eingeschlossener Autoschlüssel (Schlüssel im Auto, Schüssel im Auto, steckt im Auto) => abschleppdienst.
2. schlüsseldienst: Haus / Wohnung / Tür (Tür/Tour), Schloss zu, Schlüssel (Schlüssel/Schüssel) verloren/abgebrochen/steckt von innen NICHT im Auto. "Türen sind zu" ohne klaren Auto-Kontext => schlüsseldienst.
3. adac: Erwähnungen/Varianten: adac, a d a c, a d c, ad hoc dienst (falls offensichtlich gemeint), der ac? => adac.
4. mitarbeiter: Wunsch nach Mensch / Mitarbeiter / Arbeiter / Agent / realer Person / durchstellen / verbinden / sprechen mit jemand / menschlicher Ansprechpartner, auch verschrieben (mit Arbeiter, Arbeiter). Aussagen wie "Kann ich mit jemandem über mein Auto reden?" => mitarbeiter.
5. andere: Alles Administrative (Kündigung, Kostenfrage), unklare generische Hilfe ("Brauche Hilfe"), irrelevantes oder zu vages ohne klare Zuordnung.

PHONETIK MAPPINGS (erkenne & normalisiere):
Tour->Tür, Waage/vage->Wagen, Pfanne->Panne, Reif->Reifen, Mordor->Motor, Schüssel->Schlüssel, ab schlecht / ab sch / absch -> abschlepp, ad hoc / a d c / a d a c / ac -> adac.

PRIORITÄTEN BEI AMBIGUITÄT:
- Wenn sowohl Schlüssel- als-auch Auto-Kontext: Entscheide: "im Auto liegen gelassen / eingeschlossen" => abschleppdienst; verlorener Schlüssel ohne Innen-Auto-Hinweis => schlüsseldienst.
- Enthält klaren Wunsch nach Mensch (sprechen, verbinden) überschreibt andere Hinweise => mitarbeiter.
- Sonst fallback '{fallback}'.

Nur das Label ausgeben.
"""
        user_prompt = f"Kategorisiere diese Anfrage: \"{spoken_text}\""

        classification = _ask_grok(system_prompt, user_prompt).lower()
        result = classification if classification in choices else fallback

        duration = time.time() - start_time
        logger.info(f"Classification completed in {duration:.3f}s. Result: {result}")
        return result, duration

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"Error in classify_intent after {duration:.3f}s: {e}")
        return fallback, duration


def yes_no_question(spoken_text: str, context: str) -> tuple[bool, float]:
    """
    Determines if spoken text represents clear agreement (Yes) or not (No).
    """
    start_time = time.time()
    if not spoken_text:
        return False, 0.0

    try:
        system_prompt = """
Du entscheidest: zeigt die Antwort eine Zustimmung? Ausgabe NUR "Ja" oder "Nein".

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
        user_prompt = f"Kontext: \"{context}\" \nAntwort des Benutzers: \"{spoken_text}\". Zeigt dies eine bejahende Absicht?"

        response = _ask_grok(system_prompt, user_prompt)
        duration = time.time() - start_time

        is_agreement = response == "Ja"
        logger.info(f"Yes/No question completed in {duration:.3f}s. Result: {is_agreement}")
        return is_agreement, duration

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"Error in yes_no_question after {duration:.3f}s: {e}")
        return False, duration


def extract_location(spoken_text: str) -> tuple[str, float]:
    """
    Extracts only the address part from spoken text.
    """
    start_time = time.time()
    
    try:
        system_prompt = """
Extrahiere NUR den Adressteil aus dem gesprochenen Text. Entferne alles andere.

REGELN:
- Behalte: Straßenname, Hausnummer, PLZ, Ortsname
- Entferne: Füllwörter, Fragen, Zeitangaben, persönliche Kommentare
- Format: "Straße Hausnummer in PLZ Ort" oder verfügbare Teile davon
- Falls keine Adresse erkennbar: "Keine Adresse"

BEISPIELE:
"Ich wohne in der Güterstraße 12 in 94469 Deggendorf, wann kommst du?" -> "Güterstraße 12 in 94469 Deggendorf"
"Meine Adresse ist Hauptstraße 5, 80331 München" -> "Hauptstraße 5, 80331 München"
"Kannst du zu mir kommen? Ich bin krank." -> "Keine Adresse"
"7 9 5 9 2" -> "79592"
"Osterhofen" -> "Osterhofen"
"Ich bin auf der a3 bei Plattling" -> "Plattling"
"Ich bin in der Stadtgasse 10 in München" -> "Stadtgasse 10 in München"
"""
        user_prompt = f"Text: \"{spoken_text}\""

        result = _ask_grok(system_prompt, user_prompt)
        duration = time.time() - start_time
        logger.info(f"Location extraction completed in {duration:.3f}s. Result: {result}")
        return result.strip(), duration

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"Error extracting location after {duration:.3f}s: {e}")
        return "Keine Adresse", duration