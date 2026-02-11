"""
Comprehensive test suite for the Notdienststation system.
Tests contacts, settings, pricing, location, and full flow.

Run with: python -m twilio_agent.utils._test
"""

import datetime

import pytz


def print_section(title: str):
    print(f"\n{'='*60}")
    print(f" {title}")
    print('='*60)


def print_test(name: str):
    print(f"\n>> {name}")


def main():
    print("\n" + "="*60)
    print(" NOTDIENSTSTATION - FULL SYSTEM TEST")
    print("="*60)

    # ══════════════════════════════════════════════════════════════
    # 1. CONTACTS
    # ══════════════════════════════════════════════════════════════
    print_section("1. CONTACTS")

    from twilio_agent.utils.contacts import ContactManager, VALID_CATEGORIES

    cm = ContactManager()

    print_test("1.1 Get all contacts")
    contacts = cm.get_all_contacts()
    for cat, items in contacts.items():
        print(f"   {cat}: {len(items)} contacts")

    print_test("1.2 Locksmith contacts (with fallback info)")
    locksmiths = cm.get_contacts_for_category("locksmith")
    for c in locksmiths:
        fallback = "[FALLBACK]" if c.get("fallback") else ""
        print(f"   - {c.get('name')}: {c.get('phone')} {fallback}")
        if c.get("address"):
            print(f"     Address: {c.get('address')}")
        if c.get("zipcode"):
            print(f"     PLZ: {c.get('zipcode')}")

    print_test("1.3 Towing contacts (with fallback info)")
    towing = cm.get_contacts_for_category("towing")
    for c in towing:
        fallback = "[FALLBACK]" if c.get("fallback") else ""
        print(f"   - {c.get('name')}: {c.get('phone')} {fallback}")

    print_test("1.4 First contact (for direct transfer)")
    if locksmiths:
        first = locksmiths[0]
        print(f"   Name: {first.get('name')}")
        print(f"   Phone: {first.get('phone')}")
    else:
        print("   No contacts found")

    # ══════════════════════════════════════════════════════════════
    # 2. SETTINGS
    # ══════════════════════════════════════════════════════════════
    print_section("2. SETTINGS")

    from twilio_agent.utils.settings import SettingsManager

    sm = SettingsManager()

    print_test("2.1 Vacation mode")
    vacation = sm.get_vacation_mode()
    print(f"   Active: {vacation.get('active')}")
    print(f"   Substitute phone: {vacation.get('substitute_phone')}")

    print_test("2.2 Active hours")
    hours = sm.get_active_hours()
    print(f"   Day start: {hours.get('day_start')}:00")
    print(f"   Day end: {hours.get('day_end')}:00")

    print_test("2.3 Emergency contact")
    emergency = sm.get_emergency_contact()
    print(f"   Contact ID: {emergency.get('contact_id')}")
    print(f"   Contact name: {emergency.get('contact_name')}")

    print_test("2.4 Vacation mode status")
    if vacation.get("active") and vacation.get("substitute_phone"):
        print(f"   Vacation ACTIVE -> substitute: {vacation.get('substitute_phone')}")
    else:
        print("   Vacation NOT active -> contacts from Redis order")

    # ══════════════════════════════════════════════════════════════
    # 3. LOCATION UTILS
    # ══════════════════════════════════════════════════════════════
    print_section("3. LOCATION UTILS")

    from twilio_agent.utils.location_utils import get_geocode_result, API_KEY, BOUNDS_SW, BOUNDS_NE

    print_test("3.1 API Key status")
    print(f"   API Key set: {bool(API_KEY)}")

    print_test("3.2 Search bounds (Bayern)")
    print(f"   SW corner: {BOUNDS_SW}")
    print(f"   NE corner: {BOUNDS_NE}")

    test_addresses = ["Kempten", "94469", "Memmingen Hauptplatz"]
    for addr in test_addresses:
        print_test(f"3.3 Geocode '{addr}'")
        try:
            result = get_geocode_result(addr)
            if result:
                print(f"   Lat/Lng: {result.latitude}, {result.longitude}")
                print(f"   Address: {result.formatted_address}")
                print(f"   PLZ: {result.plz}, Ort: {result.ort}")
            else:
                print("   No result found")
        except Exception as e:
            print(f"   Error: {e}")

    # ══════════════════════════════════════════════════════════════
    # 4. PRICING
    # ══════════════════════════════════════════════════════════════
    print_section("4. PRICING")

    from twilio_agent.utils.pricing import (
        get_pricing, _is_daytime, _price, _get_service_pricing,
        _load_companies, get_price_locksmith, get_price_towing
    )

    print_test("4.1 Current time check")
    hour = datetime.datetime.now(pytz.timezone("Europe/Berlin")).hour
    is_day = _is_daytime()
    print(f"   Current hour (Berlin): {hour}")
    print(f"   Is daytime: {is_day}")
    print(f"   Price type: {'DAY' if is_day else 'NIGHT'}")

    print_test("4.2 Pricing config")
    pricing = get_pricing()
    for service in ["locksmith", "towing"]:
        svc = pricing.get(service, {})
        print(f"\n   {service.upper()}:")
        for tier in svc.get("tiers", []):
            print(f"     <{tier['minutes']}min: Day={tier['dayPrice']}EUR, Night={tier['nightPrice']}EUR")
        print(f"     Fallback: Day={svc.get('fallbackDayPrice')}EUR, Night={svc.get('fallbackNightPrice')}EUR")

    print_test("4.3 Price calculation (locksmith)")
    tiers, fallback = _get_service_pricing("locksmith")
    test_durations = [300, 600, 900, 1200, 1800, 2400]
    for seconds in test_durations:
        price, minutes = _price(seconds, tiers, fallback)
        print(f"   {seconds}s ({minutes}min) -> {price}EUR")

    print_test("4.4 Load companies (non-fallback)")
    for intent in ["locksmith", "towing"]:
        companies = _load_companies(intent, include_fallback=False)
        print(f"\n   {intent}: {len(companies)} non-fallback providers")
        for c in companies[:3]:
            print(f"     - {c.get('name')}")

    print_test("4.5 Load companies (with fallback)")
    for intent in ["locksmith", "towing"]:
        companies = _load_companies(intent, include_fallback=True)
        fallback_count = sum(1 for c in companies if c.get("fallback"))
        print(f"   {intent}: {len(companies)} total ({fallback_count} fallbacks)")

    # ══════════════════════════════════════════════════════════════
    # 5. CLOSEST PROVIDER (requires Maps API)
    # ══════════════════════════════════════════════════════════════
    print_section("5. CLOSEST PROVIDER")

    test_locations = [
        ("Deggendorf!!", 12.9779283, 48.8456799),  # (name, lng, lat)
    ]

    for name, lng, lat in test_locations:
        print_test(f"5.1 Closest locksmith from {name}")
        try:
            price, duration, provider, phone = get_price_locksmith(lng, lat)
            print(f"   Provider: {provider}")
            print(f"   Phone: {phone}")
            print(f"   Duration: {duration}min")
            print(f"   Price: {price}EUR")
        except Exception as e:
            print(f"   Error: {e}")

    print_test("5.2 Closest towing from Kempten")
    try:
        price, duration, provider, phone = get_price_towing(10.621605, 47.879637)
        print(f"   Provider: {provider}")
        print(f"   Phone: {phone}")
        print(f"   Duration: {duration}min")
        print(f"   Price: {price}EUR")
    except Exception as e:
        print(f"   Error: {e}")

    # ══════════════════════════════════════════════════════════════
    # 6. TRANSFER QUEUE SIMULATION
    # ══════════════════════════════════════════════════════════════
    print_section("6. TRANSFER QUEUE LOGIC")

    print_test("6.1 Locksmith queue order")
    print("   Queue follows Redis order (reorderable in dashboard)")
    print("   If pricing determines a provider, they go first")

    locksmiths = cm.get_contacts_for_category("locksmith")
    print(f"\n   Locksmith list ({len(locksmiths)} contacts):")
    for i, c in enumerate(locksmiths, 1):
        fallback = "[F]" if c.get("fallback") else ""
        print(f"     {i}. {c.get('name')}: {c.get('phone')} {fallback}")

    print_test("6.2 Towing queue order")
    towing = cm.get_contacts_for_category("towing")
    print(f"   Towing list ({len(towing)} contacts):")
    for i, c in enumerate(towing, 1):
        fallback = "[F]" if c.get("fallback") else ""
        print(f"     {i}. {c.get('name')}: {c.get('phone')} {fallback}")

    # ══════════════════════════════════════════════════════════════
    # 7. SUMMARY
    # ══════════════════════════════════════════════════════════════
    print_section("7. SUMMARY")

    print(f"""
   Contacts:
     - Locksmiths: {len(cm.get_contacts_for_category('locksmith'))}
     - Towing: {len(cm.get_contacts_for_category('towing'))}

   Settings:
     - Vacation mode: {'ACTIVE' if vacation.get('active') else 'OFF'}
     - Active hours: {hours.get('day_start')}:00 - {hours.get('day_end')}:00

   Current state:
     - Time: {hour}:00 (Berlin)
     - Daytime pricing: {is_day}
""")

    print("="*60)
    print(" TEST COMPLETE")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
