import yaml
from typing import Dict
import logging

logger = logging.getLogger("uvicorn")


class ContactManager:
    def __init__(self, yaml_file_path: str = "handwerker.yaml"):
        self.yaml_file_path = yaml_file_path
        self.name_to_phone = {}
        self.load_contacts()
    
    def load_contacts(self):
        with open(self.yaml_file_path, 'r', encoding='utf-8') as file:
            data = yaml.safe_load(file)
        
        # Create name to phone mapping
        for category, contacts in data.items():
            for contact in contacts:
                name = contact.get('name').strip().lower()
                phone = contact.get('phone')
                if name and phone:
                    self.name_to_phone[name] = phone
    
    def get_phone(self, name: str) -> str:
        """Get phone number by name."""
        return self.name_to_phone.get(name.lower())
    
    def get_all_contacts(self) -> Dict[str, str]:
        """Get all name to phone mappings."""
        return self.name_to_phone


# Example usage
contacts = ContactManager()

logger.info("All contacts:")
for name, phone in contacts.get_all_contacts().items():
    logger.info(f"  {name}: {phone}")

print(f"\nAndi's phone: {contacts.get_phone('Andi')}")

logger.info(f"\nAndi's phone: {contacts.get_phone('Andi')}")