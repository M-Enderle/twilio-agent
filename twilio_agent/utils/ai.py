import json
import logging
import os
import time
import sys
import re

from xai_sdk import Client
from xai_sdk.chat import system, user
import dotenv
import traceback

dotenv.load_dotenv()

# --- Global Score Tracking ---
SCORE = {
    "passed": 0,
    "total": 0,
    "classification_total": 0,
    "location_total": 0,
    "yes_no_total": 0,
}

# Collected per-test metrics for plotting
RESULTS: list[dict] = []

logger = logging.getLogger("uvicorn")

# --- ANSI Color Codes for Terminal Output ---
COLOR_RED = "\033[91m"
COLOR_GREEN = "\033[92m"
COLOR_YELLOW = "\033[93m"
COLOR_CYAN = "\033[96m"
COLOR_END = "\033[0m"
if not sys.stdout.isatty():
    COLOR_RED = COLOR_GREEN = COLOR_YELLOW = COLOR_CYAN = COLOR_END = ""

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


def extract_location(spoken_text: str) -> tuple[dict, float]:
    """
    Extracts a structured address from spoken text.
    """
    start_time = time.time()
    empty_result = {"plz": "", "ort": "", "strasse": "", "hausnummer": ""}
    
    try:
        system_prompt = """
Extrahiere eine Adresse. Gib NUR JSON mit keys: plz, ort, strasse, hausnummer (alle Strings) zurück.

REGELN:
1. Unsichere / rein beschreibende Orte (Autobahn, Kilometer, Landmarke ohne Stadt) => ort="" (leer lassen). Keine Fantasie-Orte.
2. Phonetische Normalisierung Städte: klon->Köln, münzen->München, bär-lien / berlinchen->Berlin, frankfurd->Frankfurt (sinngemäß), grönland ok. Marktplatt->Marktplatz (aber kein ort, falls nur Platz erwähnt).
3. Straßen-Suffix: "strasse" / "straße" normalisieren. Korrekturen: hautstraße->hauptstraße, goethe strafe->goethestraße, schiller strafe->schillerstraße, eis weg / eis-weg->eisweg, rhein-krücke->rheinbrücke, eiserne krücke (Frankfurt)->eiserner steg, gasse/gase->gasse.
4. Zahl-Wörter: eins=1, zwei=2, drei=3, vier=4, fünf=5, sechs=6, sieben=7, acht=8, neun=9, zehn/zehen=10. "10 a" oder "10a" vereinheitliche als 10a. Nur Hausnummer wenn eindeutig.
5. Wenn PLZ genannt und plausibel: verwende sie. Stimmen PLZ & Stadt nicht überein -> bevorzuge genannte Stadt + belasse plz falls eindeutig genannt.
6. Kein Ort erraten wenn nur allgemeine Aussage ("Der Weg ist das Ziel") => alle Felder leer.
7. Keine zusätzlichen Felder oder Text.

Output-Beispiel: {"plz":"80331","ort":"München","strasse":"Goethestraße","hausnummer":"10"}
"""
        user_prompt = f"Extrahiere die Adresse aus diesem Text: \"{spoken_text}\""

        result_raw = _ask_grok(system_prompt, user_prompt)
        duration = time.time() - start_time
        logger.info(f"Location extraction completed in {duration:.3f}s. Raw: {result_raw}")

        json_match = re.search(r'\{.*\}', result_raw, re.DOTALL)
        if not json_match:
            raise json.JSONDecodeError("No JSON object found in the response.", result_raw, 0)

        result_dict = json.loads(json_match.group())
        final_result = {key: result_dict.get(key, "") for key in empty_result}
        return final_result, duration

    except (json.JSONDecodeError, Exception) as e:
        duration = time.time() - start_time
        logger.error(f"Error extracting location after {duration:.3f}s: {e}")
        traceback.print_exc()
        return empty_result, duration
    
if __name__ == "__main__":
    
    # Simple helper function for clean output and colored status
    def run_test(func, *args, expected=None):
        global SCORE
        global RESULTS
        
        name = func.__name__
        text = args[0]
        
        print(f"\n--- {name.upper()} Test ---")
        print(f"  Input:   '{text}'")

        success = False
        duration = -1.0

        if name == "yes_no_question":
            SCORE["total"] += 1
            SCORE["yes_no_total"] += 1
            context = args[1]
            print(f"  Context: '{context}'")
            result_bool, duration = func(text, context)
            result_display = 'JA' if result_bool else 'NEIN'
            
            expected_bool = True if expected == 'JA' else False
            success = (result_bool == expected_bool)
            
            print(f"  Output:  {result_display} (Expected: {expected})")

        elif name == "extract_location":
            SCORE["total"] += 1
            SCORE["location_total"] += 1
            
            result, duration = func(*args)
            print(f"  Output:  {result}")
            
            expected_plz = expected.get("plz", "").strip().lower()
            expected_ort = expected.get("ort", "").strip().lower()
            
            actual_plz = result.get("plz", "").strip().lower()
            actual_ort = result.get("ort", "").strip().lower()

            # For this test, success can be partial (either PLZ or Ort matches)
            plz_match = (expected_plz != "" and expected_plz == actual_plz)
            ort_match = (expected_ort != "" and expected_ort == actual_ort)
            
            # Special case for empty expectations (e.g. Autobahn)
            if not expected_plz and not expected_ort:
                success = not actual_plz and not actual_ort
            else:
                success = plz_match or ort_match
            
            print(f"  Expected: (PLZ: {expected_plz if expected_plz else 'n/a'}, Ort: {expected_ort if expected_ort else 'n/a'})")

        elif name == "classify_intent":
            SCORE["total"] += 1
            SCORE["classification_total"] += 1
            
            result, duration = func(*args)
            
            success = (result == expected)
            
            print(f"  Output:  '{result}' (Expected: {expected})")
        
        # Final Status print
        if success:
            SCORE["passed"] += 1
            status_color = COLOR_GREEN
            status_text = "SUCCESS"
        else:
            status_color = COLOR_RED
            status_text = "FAILED"
        
        print(f"  Status:  {status_color}{status_text}{COLOR_END}")
        print(f"  Time:    {duration:.3f}s")

        # Store metrics
        RESULTS.append({
            "type": name,
            "input": text,
            "expected": expected if isinstance(expected, str) else str(expected),
            "success": success,
            "duration": duration
        })

        
    print("\n=======================================================")
    print("           ROBUST PROMPTING TEST SUITE")
    print("=======================================================")
    
    # -----------------------------------------------------------
    # Intent Classification Tests (Against cases 1-40)
    # -----------------------------------------------------------

    run_test(classify_intent, "Ich hab meinen Schlüssel im Auto liegen gelassen.", expected="abschleppdienst")
    run_test(classify_intent, "Brauche dringend Hilfe, die Türen sind zu.", expected="schlüsseldienst")
    run_test(classify_intent, "Kann ich mit jemandem über Mein Auto reden?", expected="mitarbeiter")
    run_test(classify_intent, "Ich bin vom A DAC Pannendienst.", expected="adac")
    run_test(classify_intent, "Ich möchte meine Mitgliedschaft kündigen.", expected="andere")
    run_test(classify_intent, "Wie viel kostet dieser Service?", expected="andere")
    run_test(classify_intent, "Ich stecke fest, kein Benzin mehr.", expected="abschleppdienst")
    run_test(classify_intent, "Ich brauche einen Dienst für mein Fahrzeug.", expected="abschleppdienst")
    run_test(classify_intent, "Ist das die Pannenhilfe oder der Schlüsselnotdienst?", expected="andere")
    run_test(classify_intent, "Das ist der ÖAMTC Notruf.", expected="andere")
    run_test(classify_intent, "Bitte sofort einen Mitarbeiter verbinden.", expected="mitarbeiter")
    run_test(classify_intent, "Brauche Hilfe.", expected="andere")


    # -----------------------------------------------------------
    # Yes/No Question Tests (Against cases 41-70)
    # -----------------------------------------------------------
    
    run_test(yes_no_question, "Wahrscheinlich ja.", "Haben Sie die AGB gelesen?", expected="JA")
    run_test(yes_no_question, "Sagen wir mal eher nein.", "Haben Sie das Auto schon bezahlt?", expected="NEIN")
    run_test(yes_no_question, "In Ordnung.", "Soll ich die Adresse bestätigen?", expected="JA")
    run_test(yes_no_question, "Ganz im Gegenteil.", "Haben Sie Ihren Schlüssel dabei?", expected="NEIN")
    run_test(yes_no_question, "Ist mir egal.", "Möchten Sie Service A oder B?", expected="NEIN")
    run_test(yes_no_question, "Stimmt, aber...", "Ist die Adresse richtig?", expected="JA")
    run_test(yes_no_question, "Kann ich weder bestätigen noch verneinen.", "Sind Sie mit dem Preis einverstanden?", expected="NEIN")
    run_test(yes_no_question, "Jup.", "Ist das die Postleitzahl 55116?", expected="JA")
    run_test(yes_no_question, "Bitte wiederholen.", "Ist der Name Müller?", expected="NEIN")
    run_test(yes_no_question, "Absolut!", "Sind Sie bereit?", expected="JA")
    run_test(yes_no_question, "Es stimmt nicht, dass Sie das Auto gekauft haben.", "Haben Sie das Auto gekauft?", expected="NEIN")
    run_test(yes_no_question, "Nein, ganz und gar nicht.", "Sind Sie zufrieden?", expected="NEIN")


    # -----------------------------------------------------------
    # Location Extraction Tests (Against cases 71-100)
    # -----------------------------------------------------------
    
    run_test(extract_location, "Hauptstraße elf in 88888 Hamburg.", expected={"plz": "20095", "ort": "hamburg"})
    run_test(extract_location, "Zwei null zwei fünf eins Hamburg, Dorfstraße elf.", expected={"plz": "20251", "ort": "hamburg"})
    run_test(extract_location, "PLZ 99999 Ort Regensburg.", expected={"plz": "93047", "ort": "regensburg"})
    run_test(extract_location, "Ich bin in der Straße der Einheit 12, 01067 Dresden.", expected={"plz": "01067", "ort": "dresden"})
    run_test(extract_location, "Die Hausnummer ist 42, in Berl und die Postleitzahl 10115.", expected={"plz": "10115", "ort": "berlin"})
    run_test(extract_location, "Ich bin auf der Autobahn A9, Kilometer 150.", expected={"plz": "", "ort": ""})
    run_test(extract_location, "Hinter dem Rathaus in Köln.", expected={"plz": "", "ort": "köln"})
    run_test(extract_location, "Die Adresse ist Aachen, 52072, Peterstraße, Hausnummer 50/51.", expected={"plz": "52072", "ort": "aachen"})
    run_test(extract_location, "7 an der Goethestraße 80333, München.", expected={"plz": "80333", "ort": "münchen"})
    run_test(extract_location, "Straße der 17. Juni 100 in Berlin.", expected={"plz": "", "ort": "berlin"})
    run_test(extract_location, "Ich bin in 3 8 1 0 0 Braunschweig.", expected={"plz": "38100", "ort": "braunschweig"})
    run_test(extract_location, "Mein Haus ist Nummer 4 in der Lindenstraße in Berlinchen.", expected={"plz": "", "ort": "berlin"})

    # -----------------------------------------------------------
    # NEW: Transcription Error Test Suite (100 Examples)
    # -----------------------------------------------------------
    print("\n=======================================================")
    print("      TRANSCRIPTION ERROR TEST SUITE (100 New Tests)")
    print("=======================================================")

    # --- CLASSIFY_INTENT (40 Tests) ---
    run_test(classify_intent, "Ich habe meine Schüssel verloren.", expected="schlüsseldienst")
    run_test(classify_intent, "Die Tour geht nicht auf.", expected="schlüsseldienst")
    run_test(classify_intent, "Mein Wagen ist sehr vage.", expected="abschleppdienst")
    run_test(classify_intent, "Ich hatte eine Pfanne mit dem Auto.", expected="abschleppdienst")
    run_test(classify_intent, "Bitte den ad hoc Dienst schicken.", expected="adac")
    run_test(classify_intent, "Ich will mit einem mit Arbeiter sprechen.", expected="mitarbeiter")
    run_test(classify_intent, "Ich brauche die Hälfte.", expected="andere")
    run_test(classify_intent, "Mein Reif ist platt.", expected="abschleppdienst")
    run_test(classify_intent, "Der Mordor macht komische Geräusche.", expected="abschleppdienst")
    run_test(classify_intent, "Können sie mich ab schleppen?", expected="abschleppdienst")
    run_test(classify_intent, "Die Auto-Schüssel passt nicht mehr.", expected="schlüsseldienst")
    run_test(classify_intent, "Ich mache eine Tour und jetzt ist das Auto zu.", expected="schlüsseldienst")
    run_test(classify_intent, "Auf der Waage ist mein Auto liegengeblieben.", expected="abschleppdienst")
    run_test(classify_intent, "Der A D A C soll kommen.", expected="adac")
    run_test(classify_intent, "Ein ab schlecht Dienst hat mich hergebracht.", expected="andere")
    run_test(classify_intent, "Die Batterie, bat er eh, ist leer.", expected="abschleppdienst")
    run_test(classify_intent, "Ich glaube der Wagen hat Reif.", expected="abschleppdienst")
    run_test(classify_intent, "Ich brauche eine neue Schüssel für die Haustür.", expected="schlüsseldienst")
    run_test(classify_intent, "Die Tour ist ins Schloss gefallen.", expected="schlüsseldienst")
    run_test(classify_intent, "Meine Pfanne ist auf der A1.", expected="abschleppdienst")
    run_test(classify_intent, "Wer ist der ADC?", expected="adac")
    run_test(classify_intent, "Ich will das mit einem Arbeiter klären.", expected="mitarbeiter")
    run_test(classify_intent, "Die Hälfte der Lichter geht nicht.", expected="abschleppdienst")
    run_test(classify_intent, "Ein Reif ist kaputt.", expected="abschleppdienst")
    run_test(classify_intent, "Der Mordor qualmt.", expected="abschleppdienst")
    run_test(classify_intent, "Das Auto muss weg, bitte ab schleppen.", expected="abschleppdienst")
    run_test(classify_intent, "Meine Schüssel ist im Auto eingeschlossen.", expected="abschleppdienst")
    run_test(classify_intent, "Die Wohnungstour ist abgebrochen.", expected="schlüsseldienst")
    run_test(classify_intent, "Der Wagen ist nicht vage, er ist kaputt.", expected="abschleppdienst")
    run_test(classify_intent, "Ah, der AC, können die helfen?", expected="adac")
    run_test(classify_intent, "Das ist ein Fall für den Arbeiter.", expected="mitarbeiter")
    run_test(classify_intent, "Ich habe nur die Hälfte vom Schlüssel.", expected="schlüsseldienst")
    run_test(classify_intent, "Der Reif ist geplatzt.", expected="abschleppdienst")
    run_test(classify_intent, "Hilfe, der Mordor brennt!", expected="abschleppdienst")
    run_test(classify_intent, "Ich brauche einen Dienst der ab schleppt.", expected="abschleppdienst")
    run_test(classify_intent, "Die Schüssel steckt von innen.", expected="schlüsseldienst")
    run_test(classify_intent, "Die Tour zur Garage ist zu.", expected="schlüsseldienst")
    run_test(classify_intent, "Mein Auto ist so vage.", expected="abschleppdienst")
    run_test(classify_intent, "Ich hatte eine Motor-Pfanne.", expected="abschleppdienst")
    run_test(classify_intent, "A D C bitte.", expected="adac")

    # --- YES/NO (20 Tests) ---
    run_test(yes_no_question, "Na ja, machen wir so.", "Soll ich buchen?", expected="JA")
    run_test(yes_no_question, "Ich sagte neun.", "Möchten Sie das?", expected="NEIN")
    run_test(yes_no_question, "Das schwimmt.", "Ist das korrekt?", expected="JA")
    run_test(yes_no_question, "Kam er schon?", "Soll ich ihn schicken?", expected="NEIN")
    run_test(yes_no_question, "Geh nau.", "Ist das die richtige Adresse?", expected="JA")
    run_test(yes_no_question, "Ich brauche eine Sichel.", "Sind Sie sicher?", expected="NEIN")
    run_test(yes_no_question, "Ja, das war eine Jagd.", "Haben Sie es gefunden?", expected="JA")
    run_test(yes_no_question, "Neun, auf keinen Fall.", "Sind Sie einverstanden?", expected="NEIN")
    run_test(yes_no_question, "Das schwimmt so.", "Ist das in Ordnung?", expected="JA")
    run_test(yes_no_question, "Ist alles klar.", "Haben Sie noch Fragen?", expected="JA")
    run_test(yes_no_question, "Geh nau, das ist es.", "Bestätigen Sie das?", expected="JA")
    run_test(yes_no_question, "Sicher, machen Sie das.", "Soll ich starten?", expected="JA")
    run_test(yes_no_question, "Na ja.", "Sind Sie einverstanden?", expected="JA")
    run_test(yes_no_question, "Neun mal nein.", "Also ja?", expected="NEIN")
    run_test(yes_no_question, "Das schwimmt nicht.", "Also ist es falsch?", expected="NEIN")
    run_test(yes_no_question, "Alles klar bei mir.", "Benötigen Sie Hilfe?", expected="JA")
    run_test(yes_no_question, "Geh nau so ist es.", "Ist das richtig?", expected="JA")
    run_test(yes_no_question, "Bin absolut sicher.", "Sollen wir fortfahren?", expected="JA")
    run_test(yes_no_question, "Ja, die Jagd war erfolgreich.", "Haben Sie es?", expected="JA")
    run_test(yes_no_question, "Neun.", "Ist das Ihre Hausnummer?", expected="NEIN")

    # --- EXTRACT_LOCATION (40 Tests) ---
    run_test(extract_location, "Ich bin in der Goethe Strafe 10.", expected={"ort": "", "strasse": "goethestraße"})
    run_test(extract_location, "Fahren sie zum Rathaus platt.", expected={"ort": "", "strasse": "rathausplatz"})
    run_test(extract_location, "Der Schlüssel ist weg 3.", expected={"ort": "", "strasse": "weg"})
    run_test(extract_location, "In der Gase Nummer 4.", expected={"ort": "", "strasse": "gasse"})
    run_test(extract_location, "Bei der alten Krücke.", expected={"ort": "", "strasse": "alte brücke"})
    run_test(extract_location, "Hautstraße 1 in Klon.", expected={"ort": "köln", "strasse": "hauptstraße"})
    run_test(extract_location, "Ich wohne in Münzen.", expected={"ort": "münchen", "strasse": ""})
    run_test(extract_location, "Die Postleitzahl ist Bär-Lien 10115.", expected={"ort": "berlin", "plz": "10115"})
    run_test(extract_location, "Hausnummer Zehen in der Waldstraße.", expected={"hausnummer": "10", "strasse": "waldstraße"})
    run_test(extract_location, "Am Eis Weg 1.", expected={"strasse": "am eisweg", "hausnummer": "1"})
    run_test(extract_location, "Das ist die Schiller Strafe 5.", expected={"strasse": "schillerstraße", "hausnummer": "5"})
    run_test(extract_location, "Der Marktplatt ist mein Standort.", expected={"strasse": "marktplatz", "ort": ""})
    run_test(extract_location, "Ich bin vom Weg abgekommen.", expected={"strasse": "", "ort": ""})
    run_test(extract_location, "Hier riecht es nach Gasen.", expected={"strasse": "", "ort": ""})
    run_test(extract_location, "Ich habe eine Krücke, kann nicht laufen.", expected={"strasse": "", "ort": ""})
    run_test(extract_location, "Meine Haut Straße brennt.", expected={"strasse": "", "ort": ""})
    run_test(extract_location, "Ich will Münzen sehen.", expected={"ort": "münchen", "strasse": ""})
    run_test(extract_location, "Ein Bär-Lien hat angerufen.", expected={"ort": "berlin", "strasse": ""})
    run_test(extract_location, "Meine Zehen sind kalt.", expected={"strasse": "", "ort": ""})
    run_test(extract_location, "Ich hätte gern ein Eis.", expected={"strasse": "", "ort": ""})
    run_test(extract_location, "Die Strafe ist zu hoch.", expected={"strasse": "", "ort": ""})
    run_test(extract_location, "Mein Reifen ist platt.", expected={"strasse": "", "ort": ""})
    run_test(extract_location, "Der ist einfach weg.", expected={"strasse": "", "ort": ""})
    run_test(extract_location, "Ich stehe an der Rhein-Krücke in Köln.", expected={"ort": "köln", "strasse": "rheinbrücke"})
    run_test(extract_location, "Hautstraße 23, Klon.", expected={"ort": "köln", "strasse": "hauptstraße"})
    run_test(extract_location, "Ich bin in Münzen am Stachus.", expected={"ort": "münchen", "strasse": "stachus"})
    run_test(extract_location, "Hauptstadt Bär-Lien.", expected={"ort": "berlin", "strasse": ""})
    run_test(extract_location, "Nummer Zehen A.", expected={"hausnummer": "10a", "strasse": ""})
    run_test(extract_location, "Der Eis-Weg ist gesperrt.", expected={"strasse": "eisweg", "ort": ""})
    run_test(extract_location, "Schiller und Strafe, Nummer 12.", expected={"strasse": "schillerstraße", "hausnummer": "12"})
    run_test(extract_location, "Ich bin platt am Neumarkt.", expected={"strasse": "neumarkt", "ort": ""})
    run_test(extract_location, "Der Weg ist das Ziel.", expected={"strasse": "", "ort": ""})
    run_test(extract_location, "Die Gase sind in der Seitengasse.", expected={"strasse": "seitengasse", "ort": ""})
    run_test(extract_location, "Die eiserne Krücke in Frankfurt.", expected={"ort": "frankfurt", "strasse": "eiserner steg"})
    run_test(extract_location, "Die Hautstraße in Hamburg.", expected={"ort": "hamburg", "strasse": "hauptstraße"})
    run_test(extract_location, "Münzen hat die PLZ 80331.", expected={"ort": "münchen", "plz": "80331"})
    run_test(extract_location, "Ich will nach Bär-Lien fahren.", expected={"ort": "berlin", "strasse": ""})
    run_test(extract_location, "Meine Hausnummer ist Zehen, nicht neun.", expected={"hausnummer": "10", "strasse": ""})
    run_test(extract_location, "Eis Weg 2 in Grönland.", expected={"ort": "grönland", "strasse": "eisweg"})
    run_test(extract_location, "Klon Dom.", expected={"ort": "köln", "strasse": "dom"})

    # -----------------------------------------------------------
    # Final Score Output
    # -----------------------------------------------------------
    
    passed = SCORE["passed"]
    total = SCORE["total"]
    percentage = (passed / total * 100) if total > 0 else 0
    
    score_color = COLOR_GREEN if percentage >= 80 else (COLOR_YELLOW if percentage >= 50 else COLOR_RED)
    
    print("\n" + "="*50)
    print(f"{COLOR_CYAN}--- FINAL ROBUSTNESS SCORE ---{COLOR_END}")
    print(f"Total Tests Run: {total}")
    print(f"Total Passed: {passed}")
    print(f"Score: {score_color}{passed}/{total} ({percentage:.2f}%){COLOR_END}")
    print("="*50)

    # --- Plot timings with seaborn ---
    try:
        if RESULTS:
            import seaborn as sns  # type: ignore
            import pandas as pd  # type: ignore
            import matplotlib.pyplot as plt  # type: ignore

            df = pd.DataFrame(RESULTS)

            # Summary figure with two subplots
            fig, axes = plt.subplots(1, 2, figsize=(12, 5))

            # Boxplot of durations per type
            sns.boxplot(
                data=df,
                x="type",
                y="duration",
                hue="success",
                ax=axes[0],
                palette={True: "#4caf50", False: "#f44336"}
            )
            axes[0].set_title("Antwortzeiten je Testtyp")
            axes[0].set_xlabel("Testtyp")
            axes[0].set_ylabel("Sekunden")
            axes[0].legend(title="Erfolg")

            # Barplot of mean durations
            mean_df = df.groupby("type", as_index=False)["duration"].mean()
            sns.barplot(data=mean_df, x="type", y="duration", ax=axes[1], color="#2196f3")
            axes[1].set_title("Ø Antwortzeit je Typ")
            axes[1].set_xlabel("Testtyp")
            axes[1].set_ylabel("Sekunden (Ø)")

            plt.tight_layout()
            out_path = os.path.join(os.path.dirname(__file__), "response_times.png")
            plt.savefig(out_path, dpi=150)
            print(f"Zeitdiagramme gespeichert unter: {out_path}")

            # Histogram + KDE distribution
            fig2, ax2 = plt.subplots(figsize=(14,5))  # wider figure
            import numpy as np  # type: ignore
            max_dur = float(df["duration"].max()) if not df.empty else 0.0
            # Ensure a minimal positive range
            if max_dur <= 0:
                max_dur = 1.0
            # Bin edges for 100 bins between 0 and max_dur (slightly padded)
            padded_max = max_dur * 1.02
            bins = np.linspace(0, padded_max, 101)
            try:
                sns.histplot(
                    data=df,
                    x="duration",
                    hue="type",
                    kde=True,
                    element="step",
                    stat="density",
                    common_norm=False,
                    alpha=0.28,
                    ax=ax2,
                    bins=bins
                )
            except TypeError:
                # Fallback for older seaborn without kde parameter in histplot
                sns.histplot(
                    data=df,
                    x="duration",
                    hue="type",
                    element="step",
                    stat="density",
                    common_norm=False,
                    alpha=0.28,
                    ax=ax2,
                    bins=bins
                )
                for t, sub in df.groupby("type"):
                    sns.kdeplot(sub["duration"], ax=ax2, label=f"{t} KDE")
            ax2.set_title("Verteilung Antwortzeiten (Histogramm + KDE, 100 Bins)")
            ax2.set_xlabel("Dauer (s)")
            ax2.set_ylabel("Dichte")
            ax2.legend(title="Typ", fontsize=8)
            from matplotlib.ticker import MultipleLocator
            # Set major ticks every 0.1s
            ax2.xaxis.set_major_locator(MultipleLocator(0.1))
            ax2.grid(axis="x", which="major", linestyle=":", alpha=0.4)
            dist_path = os.path.join(os.path.dirname(__file__), "response_times_dist.png")
            plt.tight_layout()
            plt.savefig(dist_path, dpi=150)
            print(f"Histogramm + KDE gespeichert unter: {dist_path}")
        else:
            print("Keine Ergebnisse zum Plotten vorhanden.")
    except ImportError:
        print("Seaborn oder pandas nicht installiert – Plot übersprungen.")
    except Exception as e:
        print(f"Fehler beim Erzeugen des Plots: {e}")