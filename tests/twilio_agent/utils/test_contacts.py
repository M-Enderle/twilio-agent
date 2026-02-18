"""Tests for twilio_agent.utils.contacts module."""

import json
from unittest.mock import MagicMock, patch

import pytest

from twilio_agent.utils.contacts import CONTACTS_KEY, VALID_CATEGORIES


@pytest.fixture
def mock_redis():
    """Patch the module-level redis so ContactManager.__init__ picks it up."""
    mock = MagicMock()
    with patch("twilio_agent.utils.contacts.redis", mock):
        from twilio_agent.utils.contacts import ContactManager

        yield mock, ContactManager()


def _encode_contacts(contacts: list) -> bytes:
    """Encode a list of contact dicts the same way Redis would return them."""
    return json.dumps(contacts, ensure_ascii=False).encode("utf-8")


# ── get_contacts_for_category ────────────────────────────────


class TestGetContactsForCategory:
    def test_returns_empty_list_when_no_data(self, mock_redis):
        redis_mock, cm = mock_redis
        redis_mock.get.return_value = None

        result = cm.get_contacts_for_category("locksmith")

        assert result == []
        redis_mock.get.assert_called_once_with(f"{CONTACTS_KEY}:locksmith")

    def test_parses_stored_json_correctly(self, mock_redis):
        redis_mock, cm = mock_redis
        stored = [
            {"id": "abc-123", "name": "Max Mustermann", "phone": "+4917612345678"},
            {"id": "def-456", "name": "Erika Muster", "phone": "+4917687654321"},
        ]
        redis_mock.get.return_value = _encode_contacts(stored)

        result = cm.get_contacts_for_category("locksmith")

        assert len(result) == 2
        assert result[0]["name"] == "Max Mustermann"
        assert result[1]["phone"] == "+4917687654321"


# ── get_all_contacts ────────────────────────────────────────


class TestGetAllContacts:
    def test_returns_dict_with_both_categories(self, mock_redis):
        redis_mock, cm = mock_redis

        locksmith_data = [{"id": "l1", "name": "Locksmith A", "phone": "+49111"}]
        towing_data = [{"id": "t1", "name": "Towing B", "phone": "+49222"}]

        def side_effect(key):
            if key == f"{CONTACTS_KEY}:locksmith":
                return _encode_contacts(locksmith_data)
            if key == f"{CONTACTS_KEY}:towing":
                return _encode_contacts(towing_data)
            return None

        redis_mock.get.side_effect = side_effect

        result = cm.get_all_contacts()

        assert set(result.keys()) == set(VALID_CATEGORIES)
        assert len(result["locksmith"]) == 1
        assert len(result["towing"]) == 1
        assert result["locksmith"][0]["name"] == "Locksmith A"
        assert result["towing"][0]["name"] == "Towing B"


# ── add_contact ──────────────────────────────────────────────


class TestAddContact:
    def test_assigns_uuid_and_persists(self, mock_redis):
        redis_mock, cm = mock_redis
        redis_mock.get.return_value = None  # empty category

        contact = {"name": "Neuer Kontakt", "phone": "+491761111111"}
        result = cm.add_contact("locksmith", contact)

        # A UUID id was assigned
        assert "id" in result
        assert len(result["id"]) == 36  # UUID4 format: 8-4-4-4-12
        assert result["name"] == "Neuer Kontakt"

        # Verify the contact was saved to Redis
        redis_mock.set.assert_called_once()
        saved_key = redis_mock.set.call_args[0][0]
        saved_data = json.loads(redis_mock.set.call_args[0][1])

        assert saved_key == f"{CONTACTS_KEY}:locksmith"
        assert len(saved_data) == 1
        assert saved_data[0]["id"] == result["id"]

    def test_appends_to_existing_contacts(self, mock_redis):
        redis_mock, cm = mock_redis
        existing = [{"id": "existing-1", "name": "Already There", "phone": "+49000"}]
        redis_mock.get.return_value = _encode_contacts(existing)

        new_contact = {"name": "Brand New", "phone": "+49999"}
        cm.add_contact("towing", new_contact)

        saved_data = json.loads(redis_mock.set.call_args[0][1])
        assert len(saved_data) == 2
        assert saved_data[0]["name"] == "Already There"
        assert saved_data[1]["name"] == "Brand New"


# ── update_contact ───────────────────────────────────────────


class TestUpdateContact:
    def test_modifies_existing_contact(self, mock_redis):
        redis_mock, cm = mock_redis
        stored = [
            {"id": "u1", "name": "Old Name", "phone": "+49111"},
            {"id": "u2", "name": "Other", "phone": "+49222"},
        ]
        redis_mock.get.return_value = _encode_contacts(stored)

        result = cm.update_contact("locksmith", "u1", {"name": "New Name"})

        assert result is not None
        assert result["name"] == "New Name"
        assert result["phone"] == "+49111"  # unchanged
        assert result["id"] == "u1"  # id preserved

        saved_data = json.loads(redis_mock.set.call_args[0][1])
        assert saved_data[0]["name"] == "New Name"
        assert saved_data[1]["name"] == "Other"  # other contacts untouched

    def test_does_not_overwrite_id_field(self, mock_redis):
        redis_mock, cm = mock_redis
        stored = [{"id": "original-id", "name": "Test", "phone": "+49111"}]
        redis_mock.get.return_value = _encode_contacts(stored)

        result = cm.update_contact(
            "locksmith", "original-id", {"id": "hacked-id", "name": "Updated"}
        )

        assert result["id"] == "original-id"
        assert result["name"] == "Updated"

    def test_returns_none_for_missing_contact_id(self, mock_redis):
        redis_mock, cm = mock_redis
        stored = [{"id": "real-id", "name": "Exists", "phone": "+49111"}]
        redis_mock.get.return_value = _encode_contacts(stored)

        result = cm.update_contact("locksmith", "nonexistent-id", {"name": "Ghost"})

        assert result is None
        redis_mock.set.assert_not_called()


# ── delete_contact ───────────────────────────────────────────


class TestDeleteContact:
    def test_removes_contact_and_returns_true(self, mock_redis):
        redis_mock, cm = mock_redis
        stored = [
            {"id": "d1", "name": "Keep", "phone": "+49111"},
            {"id": "d2", "name": "Delete Me", "phone": "+49222"},
        ]
        redis_mock.get.return_value = _encode_contacts(stored)

        result = cm.delete_contact("locksmith", "d2")

        assert result is True
        saved_data = json.loads(redis_mock.set.call_args[0][1])
        assert len(saved_data) == 1
        assert saved_data[0]["id"] == "d1"

    def test_returns_false_when_id_not_found(self, mock_redis):
        redis_mock, cm = mock_redis
        stored = [{"id": "d1", "name": "Only One", "phone": "+49111"}]
        redis_mock.get.return_value = _encode_contacts(stored)

        result = cm.delete_contact("locksmith", "not-a-real-id")

        assert result is False
        redis_mock.set.assert_not_called()


# ── reorder_contacts ─────────────────────────────────────────


class TestReorderContacts:
    def test_reorders_correctly(self, mock_redis):
        redis_mock, cm = mock_redis
        stored = [
            {"id": "r1", "name": "First"},
            {"id": "r2", "name": "Second"},
            {"id": "r3", "name": "Third"},
        ]
        redis_mock.get.return_value = _encode_contacts(stored)

        result = cm.reorder_contacts("locksmith", ["r3", "r1", "r2"])

        assert [c["id"] for c in result] == ["r3", "r1", "r2"]

        saved_data = json.loads(redis_mock.set.call_args[0][1])
        assert [c["id"] for c in saved_data] == ["r3", "r1", "r2"]

    def test_appends_missing_contacts_at_end(self, mock_redis):
        redis_mock, cm = mock_redis
        stored = [
            {"id": "r1", "name": "First"},
            {"id": "r2", "name": "Second"},
            {"id": "r3", "name": "Third"},
        ]
        redis_mock.get.return_value = _encode_contacts(stored)

        # Only provide two of the three ids -- r2 should be appended
        result = cm.reorder_contacts("locksmith", ["r3", "r1"])

        assert [c["id"] for c in result] == ["r3", "r1", "r2"]

    def test_ignores_unknown_ids_in_order_list(self, mock_redis):
        redis_mock, cm = mock_redis
        stored = [
            {"id": "r1", "name": "First"},
            {"id": "r2", "name": "Second"},
        ]
        redis_mock.get.return_value = _encode_contacts(stored)

        result = cm.reorder_contacts("locksmith", ["ghost-id", "r2", "r1"])

        assert [c["id"] for c in result] == ["r2", "r1"]
