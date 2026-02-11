import json
import logging
import uuid
from typing import Dict, List, Optional

from twilio_agent.actions.redis_actions import redis

logger = logging.getLogger("uvicorn")

CONFIG_PREFIX = "notdienststation:config"
CONTACTS_KEY = f"{CONFIG_PREFIX}:contacts"

VALID_CATEGORIES = ("locksmith", "towing")


class ContactManager:
    def __init__(self):
        self.redis = redis  # Use shared Redis connection from redis_actions

    # ── Contact reads ──────────────────────────────────────────────

    def get_contacts_for_category(self, category: str) -> List[dict]:
        raw = self.redis.get(f"{CONTACTS_KEY}:{category}")
        if not raw:
            return []
        return json.loads(raw.decode("utf-8"))

    def get_all_contacts(self) -> Dict[str, List[dict]]:
        return {cat: self.get_contacts_for_category(cat) for cat in VALID_CATEGORIES}

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


if __name__ == "__main__":
    print("=== Contacts Tests ===\n")
    cm = ContactManager()

    # Test get_all_contacts
    print("1. get_all_contacts():")
    contacts = cm.get_all_contacts()
    for category, items in contacts.items():
        print(f"   {category}: {len(items)} contacts")

    # Test get_contacts_for_category
    print("\n2. get_contacts_for_category('locksmith'):")
    locksmiths = cm.get_contacts_for_category("locksmith")
    for c in locksmiths[:3]:
        print(f"   - {c.get('name')}: {c.get('phone')}")
    if len(locksmiths) > 3:
        print(f"   ... and {len(locksmiths) - 3} more")

    # Test first contact (used for direct transfer)
    print("\n3. First locksmith contact:")
    if locksmiths:
        first = locksmiths[0]
        print(f"   Name: {first.get('name')}")
        print(f"   Phone: {first.get('phone')}")
    else:
        print("   No contacts found")

    # Show Redis keys
    print("\n4. Redis keys:")
    print(f"   CONTACTS_KEY: {CONTACTS_KEY}")
    print(f"   Categories: {VALID_CATEGORIES}")
