import json
import logging
import os
import time

from xai_sdk import Client
from xai_sdk.chat import system, user

logger = logging.getLogger("uvicorn")

client = Client(api_key=os.environ["XAI_API_KEY"])


def _ask_grok(system_prompt: str, user_prompt: str) -> str:
    """Shared function for Grok API calls

    Args:
        system_prompt: The system prompt to set context for the AI
        user_prompt: The user's input to be processed

    Returns:
        The AI's response as a stripped string
    """
    chat = client.chat.create(model="grok-4-fast-non-reasoning")
    chat.append(system(system_prompt))
    chat.append(user(user_prompt))
    response_grok = chat.sample()
    return response_grok.content.strip()


def classify(
    spoken_text: str,
    choices: list[str],
    fallback: str = "andere",
    additional_info: str = "",
    examples: dict = None,
) -> tuple[str, float]:
    """Classify spoken text into one of the provided categories

    Args:
        spoken_text: The text to classify
        choices: List of valid classification categories
        fallback: Default category if classification fails or is invalid
        additional_info: Additional information to add to the system prompt
        examples: Dictionary with category examples for better classification
    Returns:
        The classified category or fallback if classification fails
    """
    start_time = time.time()

    if not spoken_text or not choices:
        return fallback

    try:
        choices_str = "', '".join(choices)

        # Build examples section if provided
        examples_text = ""
        if examples:
            examples_text = "\n\nBeispiele für die Kategorien:\n"
            for category, example_list in examples.items():
                examples_text += f"- {category}: {', '.join(example_list)}\n"

        system_prompt = f"Du bist ein präzises Klassifikationssystem. Analysiere die folgende Kundenanfrage und ordne sie genau einer dieser Kategorien zu: '{choices_str}'. Berücksichtige dabei Synonyme, umgangssprachliche Ausdrücke und den Kontext. Antworte ausschließlich mit einem der genannten Begriffe, ohne zusätzliche Erklärungen. {additional_info}{examples_text}"
        user_prompt = f"Klassifiziere diese Anfrage: {spoken_text}"

        classification = _ask_grok(system_prompt, user_prompt).lower()
        result = classification if classification in choices else fallback

        duration = time.time() - start_time
        logger.info(f"Classification completed in {duration:.3f}s")

        return result, duration

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"Error classifying request after {duration:.3f}s: {e}")
        return fallback, duration


def yes_no_question(spoken_text: str, context: str) -> tuple[bool, float]:
    """Determine if spoken text represents agreement or disagreement

    Args:
        spoken_text: The text to analyze for yes/no response

    Returns:
        Tuple of (True if the text indicates agreement, False otherwise, response time in seconds)
    """
    if not spoken_text:
        return False, 0.0

    start_time = time.time()
    try:
        system_prompt = "Du bist ein Ja/Nein Klassifikationssystem. Analysiere die Eingabe und bestimme, ob sie eine Zustimmung (Ja) oder Ablehnung (Nein) ausdrückt. Berücksichtige auch Varianten wie 'ja', 'richtig', 'korrekt', 'stimmt', 'genau' für Ja und 'nein', 'falsch', 'nicht richtig', 'stimmt nicht' für Nein. Antworte ausschließlich mit 'Ja' oder 'Nein'."
        user_prompt = (
            f"Ist diese Aussage eine Zustimmung oder Ablehnung? Text: '{spoken_text}'. Kontext der Fragestellung: '{context}'"
        )

        response = _ask_grok(system_prompt, user_prompt)
        duration = time.time() - start_time
        logger.info(f"Yes/No question completed in {duration:.3f}s")
        return response == "Ja", duration
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"Error classifying yes/no question after {duration:.3f}s: {e}")
        return False, duration


def classify_intent(spoken_text: str) -> tuple[str, float]:
    """Classify the intent of the spoken text

    Args:
        spoken_text: The text to classify

    Returns:
        Tuple of (classified intent, response time in seconds)
    """
    classification, duration = classify(
        spoken_text,
        ["schlüsseldienst", "abschleppdienst", "adac", "mitarbeiter", "andere"],
        additional_info="Die Kategorie adac darf nur gewählt werden wenn im text explizit ADAC genannt wird oder eine abkürzung die ähnlich klingt!",
        examples={
            "adac": [
                "Hallo, hier ist Susanne vom ADAC. Wir haben einen Kunden mit einem problem bezüglich seines Autos.",
                "Ich rufe vom ADAC an",
                "Das ist der ADC Pannendienst",
            ],
            "abschleppdienst": [
                "Ich bin auf der Autobahn liegen geblieben.",
                "Mein Auto springt nicht mehr an.",
                "Ich hab einen platten reifen.",
                "Bin liegen geblieben, batterie leer",
                "Mein Wagen ist kaputt und muss abgeschleppt werden",
            ],
            "schlüsseldienst": [
                "Ich hab mich ausgesperrt",
                "Mein Schlüssel ist abgebrochen",
                "Ich komm nicht in meine Wohnung rein",
            ],
            "mitarbeiter": ["Ich möchte sofort mit einem Mitarbeiter sprechen"],
        },
    )
    return classification, duration


def extract_location(spoken_text: str) -> tuple[dict, float]:
    """Extract the location from the spoken text
    Args:
        spoken_text: The text to extract the location from
    Returns:
        Tuple of (extracted location dict, response time in seconds)
    """
    start_time = time.time()
    try:
        user_prompt = f"""Extrahiere den Ort aus dieser Anfrage: {spoken_text}. 
        Gebe ein json zurück, ohne ```json und ```. 
        Das json sollte die folgenden keys haben: 'plz', 'ort', 'strasse', 'hausnummer'.
        
        Beispiele:
        - "Johann Wilhelm Klein Straße 5 1 9 4 4 6 9 Deggendorf" -> {'plz': '94469', 'ort': 'Deggendorf', 'strasse': 'Johann Wilhelm Klein Straße', 'hausnummer': '51'}
        - "Hauptstraße 7 9 8 2 1 3 9 Salzburg" -> {'plz': '98213', 'ort': 'Salzburg', 'strasse': 'Hauptstraße', 'hausnummer': '7'}
        """
        result = _ask_grok("", user_prompt)
        duration = time.time() - start_time
        logger.info(f"Location extraction completed in {duration:.3f}s")
        return json.loads(result), duration
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"Error extracting location after {duration:.3f}s: {e}")
        return {"plz": "", "ort": "", "strasse": "", "hausnummer": ""}, duration


if __name__ == "__main__":
    # Test case 1: Valid classification
    result, _ = classify(
        "Ich brauche einen Schlüsseldienst",
        ["Schlüsseldienst", "Abschleppdienst"],
        "andere",
    )
    print(f"Test 1 - Expected: Schlüsseldienst, Got: {result}")

    # Test case 2: Yes/No question with positive response
    result, _ = yes_no_question("Ja, das ist richtig")
    print(f"Test 2 - Expected: True, Got: {result}")

    # Test case 3: Empty input handling
    result, _ = classify("", ["Schlüsseldienst", "Abschleppdienst"], "Andere")
    print(f"Test 3 - Expected: Andere, Got: {result}")
