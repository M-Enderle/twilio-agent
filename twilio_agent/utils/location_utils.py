import json
import logging

from Levenshtein import distance
from pydantic import BaseModel

logger = logging.getLogger("uvicorn")


def _convert_plz_to_written_numbers(plz: str):
    plz_written = ""
    for digit in str(plz):
        match digit:
            case "0":
                plz_written += "null "
            case "1":
                plz_written += "eins "
            case "2":
                plz_written += "zwei "
            case "3":
                plz_written += "drei "
            case "4":
                plz_written += "vier "
            case "5":
                plz_written += "fünf "
            case "6":
                plz_written += "sechs "
            case "7":
                plz_written += "sieben "
            case "8":
                plz_written += "acht "
            case "9":
                plz_written += "neun "
    return plz_written[:-1]


def _search_zipcode(plz: str):
    if len(plz) == 5:
        json_data = json.load(open("data/zipcodes.de.json", encoding="utf-8"))
    elif len(plz) == 4:
        json_data = json.load(open("data/zipcodes.at.json", encoding="utf-8"))

    for entry in json_data:
        if entry["zipcode"] == plz:
            return entry

    return None


def _search_city(ort: str):

    json_data_de = json.load(open("data/zipcodes.de.json", encoding="utf-8"))
    json_data_at = json.load(open("data/zipcodes.at.json", encoding="utf-8"))

    ort_lower = ort.lower()
    best_match = None
    min_distance = float("inf")

    for entry in json_data_de + json_data_at:
        place_lower = entry["place"].lower()
        levenshtein_distance = distance(ort_lower, place_lower)

        if levenshtein_distance <= 2 and levenshtein_distance < min_distance:
            min_distance = levenshtein_distance
            best_match = entry

        if place_lower == ort_lower:
            return entry

    return best_match


def check_location(plz: str, ort: str):
    if plz:
        result = _search_zipcode(plz)
        if result:
            result["written_plz"] = _convert_plz_to_written_numbers(result["zipcode"])
            return result
    elif ort:
        result = _search_city(ort)
        if result:
            result["written_plz"] = _convert_plz_to_written_numbers(result["zipcode"])
            return result
    return None


if __name__ == "__main__":
    print(check_location(None, "Deggendoof"))
