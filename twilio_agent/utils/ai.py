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

        response = _ask_grok(system_prompt, user_prompt).strip()
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

        response = _ask_grok(system_prompt, user_prompt).strip()
        if "->" in response:
            reasoning, decision = response.split("->", 1)
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

    Gebe nur die Adresse zurück, ohne zusätzliche Erklärungen.

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

        response = _ask_grok(system_prompt, user_prompt).strip()
        address = response if response and response != "Keine Adresse" else None
        return address, "Extraktion abgeschlossen.", time.time() - start_time
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"Error in extract_location after {duration:.3f}s: {e}")
        return None, f"Fehler: {e}", duration


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
        result, reasoning, duration = classify_intent(text)
        print(
            f"Case {i}: '{text}' -> {result} (Reason: {reasoning}, Time: {duration:.3f}s)"
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
        is_agreement, reasoning, duration = yes_no_question(text, context)
        print(
            f"Case {i}: '{text}' in '{context}' -> {is_agreement} (Reason: {reasoning}, Time: {duration:.3f}s)"
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
        address, reasoning, duration = extract_location(text)
        print(
            f"Case {i}: '{text}' -> '{address}' (Reason: {reasoning}, Time: {duration:.3f}s)"
        )
