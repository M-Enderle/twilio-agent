import json
import logging
import os
import uuid
from typing import Dict, List, Optional

import dotenv
import yaml
from redis import Redis

dotenv.load_dotenv()

logger = logging.getLogger("uvicorn")

REDIS_URL = os.getenv("REDIS_URL", "redis://:${REDIS_PASSWORD}@redis:6379")

CONFIG_PREFIX = "notdienststation:config"
CONTACTS_KEY = f"{CONFIG_PREFIX}:contacts"
ACTIVE_HOURS_KEY = f"{CONFIG_PREFIX}:active_hours"
VACATION_KEY = f"{CONFIG_PREFIX}:vacation"
MIGRATED_KEY = f"{CONFIG_PREFIX}:migrated"

VALID_CATEGORIES = ("locksmith", "towing")


def _get_redis() -> Redis:
    return Redis.from_url(REDIS_URL)


class ContactManager:
    def __init__(self):
        self.redis = _get_redis()

    # ── Contact reads ──────────────────────────────────────────────

    def get_contacts_for_category(self, category: str) -> List[dict]:
        raw = self.redis.get(f"{CONTACTS_KEY}:{category}")
        if not raw:
            return []
        return json.loads(raw.decode("utf-8"))

    def get_all_contacts(self) -> Dict[str, List[dict]]:
        return {cat: self.get_contacts_for_category(cat) for cat in VALID_CATEGORIES}

    def get_phone(self, name: str) -> Optional[str]:
        """Get phone number by name. Returns vacation substitute phone if global vacation active."""
        vacation = self.get_vacation_mode()
        if vacation.get("active") and vacation.get("substitute_phone"):
            return vacation["substitute_phone"]
        for category in VALID_CATEGORIES:
            for contact in self.get_contacts_for_category(category):
                if contact.get("name", "").strip().lower() == name.strip().lower():
                    return contact.get("phone")
        return None

    # ── Contact writes ─────────────────────────────────────────────

    def _save_contacts(self, category: str, contacts: List[dict]):
        self.redis.set(
            f"{CONTACTS_KEY}:{category}",
            json.dumps(contacts, ensure_ascii=False),
        )

    def add_contact(self, category: str, contact: dict) -> dict:
        contact["id"] = str(uuid.uuid4())
        contacts = self.get_contacts_for_category(category)
        contacts.append(contact)
        self._save_contacts(category, contacts)
        return contact

    def update_contact(self, category: str, contact_id: str, data: dict) -> Optional[dict]:
        contacts = self.get_contacts_for_category(category)
        for i, c in enumerate(contacts):
            if c.get("id") == contact_id:
                data.pop("id", None)
                contacts[i].update(data)
                self._save_contacts(category, contacts)
                return contacts[i]
        return None

    def delete_contact(self, category: str, contact_id: str) -> bool:
        contacts = self.get_contacts_for_category(category)
        new_contacts = [c for c in contacts if c.get("id") != contact_id]
        if len(new_contacts) == len(contacts):
            return False
        self._save_contacts(category, new_contacts)
        return True

    def reorder_contacts(self, category: str, ids: List[str]) -> List[dict]:
        contacts = self.get_contacts_for_category(category)
        by_id = {c["id"]: c for c in contacts}
        reordered = [by_id[cid] for cid in ids if cid in by_id]
        # Append any contacts not in the provided list at the end
        seen = set(ids)
        for c in contacts:
            if c["id"] not in seen:
                reordered.append(c)
        self._save_contacts(category, reordered)
        return reordered

    # ── Global vacation mode ──────────────────────────────────────

    def get_vacation_mode(self) -> dict:
        raw = self.redis.get(VACATION_KEY)
        if not raw:
            return {"active": False, "substitute_phone": "", "note": ""}
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
            return {"day_start": 7, "day_end": 20, "twenty_four_seven": False}
        return json.loads(raw.decode("utf-8"))

    def set_active_hours(self, config: dict):
        self.redis.set(
            ACTIVE_HOURS_KEY,
            json.dumps(config, ensure_ascii=False),
        )

    # ── Migration ──────────────────────────────────────────────────

    def migrate_from_yaml(self, yaml_path: str = "handwerker.yaml"):
        if self.redis.get(MIGRATED_KEY):
            logger.info("Contacts already migrated to Redis, skipping.")
            return

        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except FileNotFoundError:
            logger.warning("handwerker.yaml not found, skipping migration.")
            return

        for category, contacts in data.items():
            migrated = []
            for contact in contacts:
                migrated.append(
                    {
                        "id": str(uuid.uuid4()),
                        "name": contact.get("name", ""),
                        "phone": contact.get("phone", ""),
                        "address": contact.get("adress", contact.get("address", "")),
                        "zipcode": contact.get("zipcode", ""),
                        "fallback": contact.get("fallback", False),
                    }
                )
            self._save_contacts(category, migrated)

        self.redis.set(MIGRATED_KEY, "1")
        logger.info("Successfully migrated contacts from YAML to Redis.")


if __name__ == "__main__":
    cm = ContactManager()
    cm.migrate_from_yaml()
    print(cm.get_all_contacts())
    print(cm.get_phone("Andi"))
