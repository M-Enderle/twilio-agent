import logging
from typing import Optional, List
import json

from pydantic import BaseModel, SecretStr, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from twilio_agent.actions.redis_actions import redis

logger = logging.getLogger("uvicorn")

VALID_SERVICES = ["schluessel-allgaeu", "notdienst-schluessel", "notdienst-abschlepp"]
DEFAULT_ANNOUNCEMENTS = {
    "greeting": "Hallo! Wie kann ich Ihnen heute helfen?",
    "intent_prompt": "Bitte beschreiben Sie Ihr Anliegen kurz.",
    "intent_not_understood": "Ich habe Sie leider nicht verstanden. Könnten Sie das bitte wiederholen?",
    "intent_failed": "Es tut mir leid, ich konnte Ihr Anliegen nicht erfassen.",
    "address_request": "An welcher Adresse benötigen Sie Hilfe?",
    "address_processing": "Einen Moment, ich prüfe die Verfügbarkeit an Ihrer Adresse.",
    "address_confirm": "Habe ich das richtig verstanden?",
    "address_confirm_prompt": "Ist die Adresse korrekt?",
    "zipcode_request": "Wie lautet die Postleitzahl?",
    "sms_offer": "Soll ich Ihnen ein Angebot per SMS schicken?",
    "sms_confirm_prompt": "Möchten Sie das Angebot erhalten?",
    "sms_declined": "In Ordnung, kein Problem.",
    "sms_sent": "Die SMS wurde versendet.",
    "sms_text": "Hier ist Ihr Angebot.",
    "price_quote": "Der Preis beträgt etwa {price} Euro.",
    "yes_no_prompt": "Bitte antworten Sie mit Ja oder Nein.",
    "transfer_message": "Ich verbinde Sie jetzt mit einem verfügbaren Partner.",
    "goodbye": "Auf Wiederhören!",
    "all_busy": "Leider sind aktuell alle Partner im Einsatz.",
    "no_input": "Ich habe keine Eingabe erhalten.",
    "outbound_greeting": "Hallo, hier ist der Notdienst.",
    "outbound_yes_no": "Möchten Sie den Auftrag annehmen?",
    "driver_sms": "Ein neuer Auftrag für Sie.",
}

# ── Data Models ────────────────────────────────────────────────────

class PhoneNumber(BaseModel):
    phone_number: str = ""

class EmergencyContact(BaseModel):
    name: str = ""
    phone: str = ""

class LocationContact(BaseModel):
    """A contact person at a location."""
    name: str = ""
    phone: str = ""
    position: int = 0  # Order for call routing

class Location(BaseModel):
    """A service provider location with coordinates and contacts."""
    id: Optional[str] = None
    name: str = ""  # Required - location/business name
    address: str = ""
    zipcode: str | int = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    contacts: List[LocationContact] = Field(default_factory=list)

class DirectForwarding(BaseModel):
    active: bool = False
    forward_phone: str = ""
    start_hour: float = 0.0
    end_hour: float = 6.0

class ActiveHours(BaseModel):
    day_start: int = 8
    day_end: int = 20

class PricingTier(BaseModel):
    minutes: int
    dayPrice: int
    nightPrice: int

class Pricing(BaseModel):
    tiers: List[PricingTier] = Field(default_factory=list)
    fallbackDayPrice: int = 0
    fallbackNightPrice: int = 0

class Announcements(BaseModel):
    greeting: str = DEFAULT_ANNOUNCEMENTS["greeting"]
    intent_prompt: str = DEFAULT_ANNOUNCEMENTS["intent_prompt"]
    intent_not_understood: str = DEFAULT_ANNOUNCEMENTS["intent_not_understood"]
    intent_failed: str = DEFAULT_ANNOUNCEMENTS["intent_failed"]
    address_request: str = DEFAULT_ANNOUNCEMENTS["address_request"]
    address_processing: str = DEFAULT_ANNOUNCEMENTS["address_processing"]
    address_confirm: str = DEFAULT_ANNOUNCEMENTS["address_confirm"]
    address_confirm_prompt: str = DEFAULT_ANNOUNCEMENTS["address_confirm_prompt"]
    zipcode_request: str = DEFAULT_ANNOUNCEMENTS["zipcode_request"]
    sms_offer: str = DEFAULT_ANNOUNCEMENTS["sms_offer"]
    sms_confirm_prompt: str = DEFAULT_ANNOUNCEMENTS["sms_confirm_prompt"]
    sms_declined: str = DEFAULT_ANNOUNCEMENTS["sms_declined"]
    sms_sent: str = DEFAULT_ANNOUNCEMENTS["sms_sent"]
    sms_text: str = DEFAULT_ANNOUNCEMENTS["sms_text"]
    price_quote: str = DEFAULT_ANNOUNCEMENTS["price_quote"]
    yes_no_prompt: str = DEFAULT_ANNOUNCEMENTS["yes_no_prompt"]
    transfer_message: str = DEFAULT_ANNOUNCEMENTS["transfer_message"]
    goodbye: str = DEFAULT_ANNOUNCEMENTS["goodbye"]
    all_busy: str = DEFAULT_ANNOUNCEMENTS["all_busy"]
    no_input: str = DEFAULT_ANNOUNCEMENTS["no_input"]
    outbound_greeting: str = DEFAULT_ANNOUNCEMENTS["outbound_greeting"]
    outbound_yes_no: str = DEFAULT_ANNOUNCEMENTS["outbound_yes_no"]
    driver_sms: str = DEFAULT_ANNOUNCEMENTS["driver_sms"]


# ── Environment Settings ──────────────────────────────────────────

class EnvSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # API Keys & Secrets
    TELEGRAM_BOT_TOKEN: Optional[SecretStr] = None
    TELEGRAM_CHAT_ID: Optional[str] = None
    MAPS_API_KEY: Optional[SecretStr] = None
    XAI_API_KEY: Optional[SecretStr] = None
    BASETEN_API_KEY: Optional[SecretStr] = None
    ELEVENLABS_API_KEY: Optional[SecretStr] = None
    SECRET_KEY: SecretStr = SecretStr("insecure-default-key")

    # Twilio
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: SecretStr = SecretStr("")
    TWILIO_PHONE_NUMBER: str = ""
    NOTDIENSTSTATION_PHONE_NUMBER: Optional[str] = None

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # App Config
    DEBUG: bool = False
    ENVIRONMENT: str = "production"
    DOMAIN: str = "localhost"
    SERVER_URL: Optional[str] = None


# ── Service Settings Manager ──────────────────────────────────────

class ServiceSettings:
    def __init__(self, service_id: str):
        self.service_id = service_id
        self._redis = redis
        self._prefix = f"notdienststation:config:{service_id}"

    def _get(self, key: str, model: type[BaseModel]) -> BaseModel:
        raw = self._redis.get(f"{self._prefix}:{key}")
        if raw:
            return model.model_validate_json(raw)
        return model()

    def _set(self, key: str, value: BaseModel):
        self._redis.set(f"{self._prefix}:{key}", value.model_dump_json())

    def _get_locations(self) -> List[Location]:
        key = f"notdienststation:config:locations:{self.service_id}"
        raw = self._redis.get(key)
        if not raw:
            return []

        try:
            items = json.loads(raw)
            # Validate list of dicts into List[Location]
            return [Location.model_validate(item) for item in items]
        except Exception as e:
            logger.error(f"Error parsing locations for {self.service_id}: {e}")
            return []

    def _set_locations(self, values: List[Location]):
        key = f"notdienststation:config:locations:{self.service_id}"
        # Serialize list of models
        data = [loc.model_dump(mode='json') for loc in values]
        self._redis.set(key, json.dumps(data, ensure_ascii=False))

    @property
    def locations(self) -> List[Location]:
        return self._get_locations()

    @locations.setter
    def locations(self, value: List[Location]):
        self._set_locations(value)

    @property
    def phone_number(self) -> PhoneNumber:
        return self._get("phone_number", PhoneNumber)

    @phone_number.setter
    def phone_number(self, value: PhoneNumber):
        self._set("phone_number", value)

    @property
    def emergency_contact(self) -> EmergencyContact:
        return self._get("emergency_contact", EmergencyContact)

    @emergency_contact.setter
    def emergency_contact(self, value: EmergencyContact):
        self._set("emergency_contact", value)

    @property
    def direct_forwarding(self) -> DirectForwarding:
        return self._get("direct_forwarding", DirectForwarding)

    @direct_forwarding.setter
    def direct_forwarding(self, value: DirectForwarding):
        self._set("direct_forwarding", value)

    @property
    def active_hours(self) -> ActiveHours:
        return self._get("active_hours", ActiveHours)

    @active_hours.setter
    def active_hours(self, value: ActiveHours):
        self._set("active_hours", value)

    @property
    def pricing(self) -> Pricing:
        return self._get("pricing", Pricing)

    @pricing.setter
    def pricing(self, value: Pricing):
        self._set("pricing", value)

    @property
    def announcements(self) -> Announcements:
        return self._get("announcements", Announcements)

    @announcements.setter
    def announcements(self, value: Announcements):
        self._set("announcements", value)


class GlobalSettings:
    def __init__(self):
        self.env = EnvSettings()
        self._redis = redis

    def service(self, service_id: str) -> ServiceSettings:
        return ServiceSettings(service_id)

    @property
    def direct_forwarding(self) -> DirectForwarding:
        """Get global direct forwarding settings."""
        raw = self._redis.get("notdienststation:config:global:direct_forwarding")
        if raw:
            return DirectForwarding.model_validate_json(raw)
        return DirectForwarding()

    @direct_forwarding.setter
    def direct_forwarding(self, value: DirectForwarding):
        """Set global direct forwarding settings."""
        self._redis.set("notdienststation:config:global:direct_forwarding", value.model_dump_json())

settings = GlobalSettings()

if __name__ == "__main__":
    print(settings.service("schluessel-allgaeu").locations)
