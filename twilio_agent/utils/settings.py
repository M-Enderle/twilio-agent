import json
import logging

from twilio_agent.actions.redis_actions import redis

logger = logging.getLogger("uvicorn")

CONFIG_PREFIX = "notdienststation:config"
CONTACTS_KEY = f"{CONFIG_PREFIX}:contacts"
ACTIVE_HOURS_KEY = f"{CONFIG_PREFIX}:active_hours"
VACATION_KEY = f"{CONFIG_PREFIX}:vacation"
EMERGENCY_CONTACT_KEY = f"{CONFIG_PREFIX}:emergency_contact"
DIRECT_FORWARDING_KEY = f"{CONFIG_PREFIX}:direct_forwarding"
MIGRATED_KEY = f"{CONFIG_PREFIX}:migrated"

VALID_CATEGORIES = ("locksmith", "towing")


class SettingsManager:
    def __init__(self):
        self.redis = redis

    # ── Global vacation mode ──────────────────────────────────────

    def get_vacation_mode(self) -> dict:
        raw = self.redis.get(VACATION_KEY)
        if not raw:
            return {"active": False, "substitute_phone": ""}
        return json.loads(raw.decode("utf-8"))

    def set_vacation_mode(self, config: dict):
        self.redis.set(
            VACATION_KEY,
            json.dumps(config, ensure_ascii=False),
        )

    # ── Active hours ───────────────────────────────────────────────

    def get_active_hours(self) -> dict:
        raw = self.redis.get(ACTIVE_HOURS_KEY)
        if not raw:
            return {"day_start": 7, "day_end": 20}
        return json.loads(raw.decode("utf-8"))

    def set_active_hours(self, config: dict):
        self.redis.set(
            ACTIVE_HOURS_KEY,
            json.dumps(config, ensure_ascii=False),
        )

    # ── Emergency contact ──────────────────────────────────────────

    def get_emergency_contact(self) -> dict:
        raw = self.redis.get(EMERGENCY_CONTACT_KEY)
        if not raw:
            return {"contact_id": "", "contact_name": ""}
        return json.loads(raw.decode("utf-8"))

    def set_emergency_contact(self, config: dict):
        self.redis.set(
            EMERGENCY_CONTACT_KEY,
            json.dumps(config, ensure_ascii=False),
        )

    # ── Direct forwarding ───────────────────────────────────────────

    def get_direct_forwarding(self) -> dict:
        raw = self.redis.get(DIRECT_FORWARDING_KEY)
        if not raw:
            return {"active": False, "forward_phone": "", "start_hour": 0.0, "end_hour": 6.0}
        data = json.loads(raw.decode("utf-8"))
        data["start_hour"] = float(data.get("start_hour", 0))
        data["end_hour"] = float(data.get("end_hour", 6))
        return data

    def set_direct_forwarding(self, config: dict):
        self.redis.set(
            DIRECT_FORWARDING_KEY,
            json.dumps(config, ensure_ascii=False),
        )


if __name__ == "__main__":
    print("=== Settings Tests ===\n")
    sm = SettingsManager()

    # Test vacation mode
    print("\n2. get_vacation_mode():")
    vacation = sm.get_vacation_mode()
    print(f"   Active: {vacation.get('active')}")
    print(f"   Substitute phone: {vacation.get('substitute_phone')}")

    # Test active hours
    print("\n3. get_active_hours():")
    hours = sm.get_active_hours()
    print(f"   Day start: {hours.get('day_start')}")
    print(f"   Day end: {hours.get('day_end')}")

    # Test emergency contact
    print("\n4. get_emergency_contact():")
    emergency = sm.get_emergency_contact()
    print(f"   Contact ID: {emergency.get('contact_id')}")
    print(f"   Contact name: {emergency.get('contact_name')}")

    # Test direct forwarding
    print("\n5. get_direct_forwarding():")
    forwarding = sm.get_direct_forwarding()
    print(f"   Active: {forwarding.get('active')}")
    print(f"   Forward phone: {forwarding.get('forward_phone')}")
    print(f"   Start hour: {forwarding.get('start_hour')}")
    print(f"   End hour: {forwarding.get('end_hour')}")

    # Show Redis keys
    print("\n6. Redis keys:")
    print(f"   VACATION_KEY: {VACATION_KEY}")
    print(f"   ACTIVE_HOURS_KEY: {ACTIVE_HOURS_KEY}")
    print(f"   EMERGENCY_CONTACT_KEY: {EMERGENCY_CONTACT_KEY}")
    print(f"   DIRECT_FORWARDING_KEY: {DIRECT_FORWARDING_KEY}")
