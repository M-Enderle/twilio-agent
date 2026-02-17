import logging
from typing import Optional, List
import json

from pydantic import BaseModel, SecretStr, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from twilio_agent.actions.redis_actions import redis

logger = logging.getLogger("uvicorn")

VALID_SERVICES = ["schluessel-allgaeu", "notdienst-schluessel", "notdienst-abschlepp"]
DEFAULT_ANNOUNCEMENTS = {
    # Begrüßung
    "greeting": "Hallo! Wie kann ich Ihnen heute helfen?",
    # Adresse erfassen
    "address_request": "An welcher Adresse benötigen Sie Hilfe?",
    "address_processing": "Einen Moment, ich prüfe die Verfügbarkeit an Ihrer Adresse.",
    "address_confirm": "Habe ich das richtig verstanden?",
    "address_confirm_prompt": "Bitte bestätigen Sie mit ja oder nein, ob die Adresse korrekt ist.",
    # PLZ Fallback
    "zipcode_request": "Bitte geben Sie die Postleitzahl über den Nummernblock ein.",
    "plz_invalid_format": "Die Postleitzahl konnte nicht erkannt werden. Bitte versuchen Sie es erneut.",
    "plz_outside_area": "Diese Postleitzahl liegt außerhalb unseres Servicegebiets.",
    "plz_not_found": "Diese Postleitzahl konnte nicht gefunden werden.",
    # SMS Standort
    "sms_offer": "Wir können Ihnen eine SMS mit einem Standort-Link zusenden. Möchten Sie das?",
    "sms_sent_confirmation": "Ich habe Ihnen eine SMS mit einem Link zum Teilen Ihres Standorts gesendet. Auf Wiederhören.",
    # Preisangebot
    "price_offer": "Wir können Ihnen einen Dienstleister für {price_words} Euro anbieten. Die Ankunftszeit beträgt etwa {minutes_words} Minuten.",
    "price_offer_prompt": "Möchten Sie mit dem Dienstleister verbunden werden? Bitte antworten Sie mit ja oder nein.",
    "connection_declined": "Verstanden. Gibt es noch etwas, womit ich Ihnen helfen kann?",
    "connection_timeout": "Ich habe Ihre Antwort nicht verstanden.",
    # Transfer
    "transfer_message": "Ich verbinde Sie jetzt.",
}

# ── Error Models ───────────────────────────────────────────────────

class HumanAgentRequested(Exception):
    """Raised when the user explicitly requests a human agent."""
    pass

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
    # Begrüßung
    greeting: str = DEFAULT_ANNOUNCEMENTS["greeting"]
    # Adresse erfassen
    address_request: str = DEFAULT_ANNOUNCEMENTS["address_request"]
    address_processing: str = DEFAULT_ANNOUNCEMENTS["address_processing"]
    address_confirm: str = DEFAULT_ANNOUNCEMENTS["address_confirm"]
    address_confirm_prompt: str = DEFAULT_ANNOUNCEMENTS["address_confirm_prompt"]
    # PLZ Fallback
    zipcode_request: str = DEFAULT_ANNOUNCEMENTS["zipcode_request"]
    plz_invalid_format: str = DEFAULT_ANNOUNCEMENTS["plz_invalid_format"]
    plz_outside_area: str = DEFAULT_ANNOUNCEMENTS["plz_outside_area"]
    plz_not_found: str = DEFAULT_ANNOUNCEMENTS["plz_not_found"]
    # SMS Standort
    sms_offer: str = DEFAULT_ANNOUNCEMENTS["sms_offer"]
    sms_sent_confirmation: str = DEFAULT_ANNOUNCEMENTS["sms_sent_confirmation"]
    # Preisangebot
    price_offer: str = DEFAULT_ANNOUNCEMENTS["price_offer"]
    price_offer_prompt: str = DEFAULT_ANNOUNCEMENTS["price_offer_prompt"]
    connection_declined: str = DEFAULT_ANNOUNCEMENTS["connection_declined"]
    connection_timeout: str = DEFAULT_ANNOUNCEMENTS["connection_timeout"]
    # Transfer
    transfer_message: str = DEFAULT_ANNOUNCEMENTS["transfer_message"]

class TransferSettings(BaseModel):
    """Settings for call transfer behavior."""
    ring_timeout: int = 15  # Seconds to ring before trying next contact


# ── Environment Settings ──────────────────────────────────────────

class EnvSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── API Keys & Secrets ───────────────────────────────────
    SECRET_KEY: SecretStr = SecretStr("insecure-default-key")
    MAPS_API_KEY: Optional[SecretStr] = None

    # ── AI / LLM ────────────────────────────────────────────
    XAI_API_KEY: Optional[SecretStr] = None
    XAI_MODEL: str = "grok-4-fast-non-reasoning"
    BASETEN_API_KEY: Optional[SecretStr] = None
    BASETEN_BASE_URL: str = "https://inference.baseten.co/v1"
    BASETEN_MODEL: str = "openai/gpt-oss-120b"

    # ── Telegram ────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN: Optional[SecretStr] = None  # Legacy/fallback
    TELEGRAM_CHAT_IDS: str = ""  # Comma-separated list of chat IDs

    # Service-specific bot tokens (all use same TELEGRAM_CHAT_IDS)
    TELEGRAM_BOT_TOKEN_SCHLUESSEL_ALLGAEU: Optional[SecretStr] = None
    TELEGRAM_BOT_TOKEN_NOTDIENST_SCHLUESSEL: Optional[SecretStr] = None
    TELEGRAM_BOT_TOKEN_NOTDIENST_ABSCHLEPP: Optional[SecretStr] = None

    # ── Twilio ──────────────────────────────────────────────
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: SecretStr = SecretStr("")
    TWILIO_PHONE_NUMBER: str = ""
    NOTDIENSTSTATION_PHONE_NUMBER: Optional[str] = None
    TWILIO_RECORDING_ACCOUNT: Optional[str] = None
    TWILIO_ACCOUNT_SID_RO: Optional[str] = None
    TWILIO_AUTH_TOKEN_RO: Optional[SecretStr] = None

    # ── ElevenLabs ──────────────────────────────────────────
    ELEVENLABS_API_KEY: Optional[SecretStr] = None
    ELEVENLABS_VOICE_ID: str = "kaGxVtjLwllv1bi2GFag"
    ELEVENLABS_TTS_MODEL: str = "eleven_v3"
    ELEVENLABS_STT_MODEL: str = "scribe_v2"
    ELEVENLABS_STT_URL: str = "https://api.elevenlabs.io/v1/speech-to-text"

    # ── Redis ───────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379"

    # ── App Config ──────────────────────────────────────────
    DEBUG: bool = False
    ENVIRONMENT: str = "production"
    DOMAIN: str = "localhost"
    SERVER_URL: Optional[str] = None
    DASHBOARD_URL: Optional[str] = None


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

    @property
    def transfer_settings(self) -> TransferSettings:
        return self._get("transfer_settings", TransferSettings)

    @transfer_settings.setter
    def transfer_settings(self, value: TransferSettings):
        self._set("transfer_settings", value)


class GlobalSettings:
    def __init__(self):
        self.env = EnvSettings()
        self._redis = redis

    def service(self, service_id: str) -> ServiceSettings:
        return ServiceSettings(service_id)

    def get_telegram_chat_ids(self) -> list[str]:
        """Get list of Telegram chat IDs from the comma-separated env variable."""
        return [cid.strip() for cid in self.env.TELEGRAM_CHAT_IDS.split(",") if cid.strip()]

    def get_telegram_bot_token(self, service_id: str) -> Optional[str]:
        """Get the Telegram bot token for a specific service from environment variables."""
        token_map = {
            "schluessel-allgaeu": self.env.TELEGRAM_BOT_TOKEN_SCHLUESSEL_ALLGAEU,
            "notdienst-schluessel": self.env.TELEGRAM_BOT_TOKEN_NOTDIENST_SCHLUESSEL,
            "notdienst-abschlepp": self.env.TELEGRAM_BOT_TOKEN_NOTDIENST_ABSCHLEPP,
        }

        token = token_map.get(service_id)
        if token:
            return token.get_secret_value()

        # Fallback to legacy token
        if self.env.TELEGRAM_BOT_TOKEN:
            return self.env.TELEGRAM_BOT_TOKEN.get_secret_value()

        return None

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
