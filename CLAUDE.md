# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A production-ready Twilio-powered intelligent voice and SMS assistant for emergency services (locksmith and towing). Built with a FastAPI backend and SvelteKit dashboard, containerized for deployment.

**Services:** `schluessel-allgaeu`, `notdienst-schluessel`, `notdienst-abschlepp`

## Common Commands

### Backend (Python/FastAPI)

**Development:**
```bash
# Start development server with hot reload
uvicorn twilio_agent.main:app --reload

# Start development server with scripts
./scripts/dev-start.sh
```

**Testing:**
```bash
# Run all tests
poetry run pytest

# Run tests with verbose output
poetry run pytest -v

# Run specific test file
poetry run pytest tests/twilio_agent/utils/test_contacts.py

# Run specific test function
poetry run pytest tests/twilio_agent/utils/test_contacts.py::test_function_name

# Run tests matching a keyword
poetry run pytest -k "keyword"
```

**Code formatting:**
```bash
# Format code with black
poetry run black twilio_agent/

# Sort imports with isort
poetry run isort twilio_agent/
```

**Dependencies:**
```bash
# Install dependencies
poetry install

# Add new dependency
poetry add package-name

# Add dev dependency
poetry add --group dev package-name
```

### Frontend (SvelteKit Dashboard)

Located in `dashboard/` directory.

**Development:**
```bash
cd dashboard
npm run dev        # Start dev server
npm run build      # Build for production
npm run preview    # Preview production build
npm run check      # Type-check
```

### Docker/Production

```bash
# Start Redis for local development
docker-compose up -d redis

# View logs
docker-compose logs -f app

# Restart services
docker-compose restart

# Production deployment
./scripts/deploy.sh your-domain.com your-email@example.com
```

## Architecture

### High-Level Structure

The application uses a **modular conversation flow** architecture where each step in the phone conversation is handled by a dedicated flow module:

```
┌─────────────────────────────────────────────────────────────┐
│  twilio_agent/main.py                                       │
│  - FastAPI app entry point                                  │
│  - Registers all routers (conversation, dashboard, etc.)    │
└─────────────────────────────────────────────────────────────┘
                           │
           ┌───────────────┴───────────────┐
           │                               │
┌──────────▼──────────┐        ┌──────────▼──────────┐
│ conversation_flow.py│        │ api/dashboard.py    │
│ (Main orchestrator) │        │ (Dashboard API)     │
└─────────────────────┘        └─────────────────────┘
           │
           └─────► flow/ modules (step handlers)
                   ├── entry.py       - Initial greeting
                   ├── address.py     - Address collection & validation
                   ├── plz.py         - ZIP code fallback flow
                   ├── pricing.py     - Price calculation & offer
                   └── transfer.py    - Call transfer handling
```

### Conversation Flow

The conversation_flow.py file orchestrates the entire call flow by routing incoming webhook requests to appropriate handlers:

1. **Entry** (`/incoming-call` → flow/entry.py) - Greet caller, check for direct transfer or previous transfers
2. **Address Collection** (`/ask-adress` → flow/address.py) - Collect and validate address via AI speech-to-text
3. **Address Processing** (`/process-address` → flow/address.py) - Geocode and confirm address
4. **PLZ Fallback** (`/ask-plz` → flow/plz.py) - If address fails, ask for ZIP code via keypad
5. **SMS Location** (`/ask-send-sms` → flow/plz.py) - Offer to send SMS with location sharing link
6. **Pricing** (`/start-pricing` → flow/pricing.py) - Calculate price and travel time, offer connection
7. **Transfer** (`/parse-transfer-call` → flow/transfer.py) - Connect caller to service provider

Each flow module returns TwiML responses that control the call (say, gather, redirect, dial).

### Key Directories

**twilio_agent/** - Main Python package
- `main.py` - FastAPI app initialization with background scheduler startup/shutdown
- `scheduler.py` - Background task scheduler (APScheduler) for daily territory calculations
- `conversation_flow.py` - Main router orchestrating all conversation endpoints
- `settings.py` - Multi-service configuration management via Redis
- `flow/` - Modular conversation step handlers
- `actions/` - Integration modules (Twilio, Redis, Telegram, Recording, Location)
- `utils/` - Utilities (AI/LLM, location geocoding, pricing, contacts)
- `api/` - Dashboard REST API for managing settings and viewing calls

**dashboard/** - SvelteKit frontend
- `src/routes/` - Pages (anrufe, standorte, preise, einstellungen, ansagen)
- `src/lib/` - Shared components and API client
- `src/lib/components/StandortMap.svelte` - Map display (loads cached territories, no client-side calculation)

**data/** - ZIP code databases for location services

**templates/** - HTML templates for location sharing web interface

### Settings Architecture

Settings are **per-service** and stored in **Redis**:

- `settings.service(service_id).locations` - Service provider locations with contacts
- `settings.service(service_id).phone_number` - Service phone number
- `settings.service(service_id).emergency_contact` - Fallback contact
- `settings.service(service_id).direct_forwarding` - Direct forwarding rules (time-based)
- `settings.service(service_id).active_hours` - Active hours configuration
- `settings.service(service_id).pricing` - Pricing tiers and fallbacks
- `settings.service(service_id).announcements` - Customizable voice prompts

Access via `settings.service("schluessel-allgaeu").announcements.greeting` etc.

### State Management

Call state is stored in Redis with keys like:
- `notdienststation:anrufe:{phone}:*` - Active call data
- `notdienststation:verlauf:{phone}:{timestamp}:*` - Call history (info, messages, recordings)
- `notdienststation:config:{service_id}:*` - Service configuration
- `notdienststation:{service_id}:territories` - Cached territory border calculations

Use `twilio_agent/actions/redis_actions.py` helpers:
- `save_job_info(phone, key, value)` - Save call metadata
- `get_job_info(phone, key)` - Retrieve call metadata
- `agent_message(phone, text)` - Log assistant message

### Background Tasks

**Territory Calculation** (`twilio_agent/scheduler.py`):
- Runs daily at 4:00 AM automatically
- Calculates drive-time based territory borders for all services using OSRM API
- Results cached in Redis with key `notdienststation:{service_id}:territories`
- Frontend only displays cached territories (no client-side calculation)
- Manual trigger available via API: `POST /api/dashboard/services/{service_id}/territories/recalculate`

### AI Integration

The system uses multiple LLM providers configured in `settings.py`:
- **XAI (Grok)** - Primary LLM for intent classification and parsing
- **Baseten** - Alternative LLM provider
- **ElevenLabs** - Text-to-speech (TTS) and speech-to-text (STT)

AI utilities in `twilio_agent/utils/ai.py`:
- `llm_prompt()` - Execute LLM prompts with structured output
- Intent classification, address parsing, confirmation parsing

Audio handling in `twilio_agent/utils/eleven.py`:
- `text_to_speech()` - Convert text to audio with caching
- `speech_to_text()` - Transcribe audio files

## Important Patterns

### Flow Handler Pattern

Each flow module exports handler functions that:
1. Extract call info via `call_info(request)`
2. Use `new_response()` context manager to build TwiML
3. Use `say(response, text)` to speak to caller
4. Use `gather()` to collect user input (speech or keypad)
5. Log to Redis via `save_job_info()` and `agent_message()`
6. Return `send_request(request, response)` to send TwiML

Example:
```python
async def my_handler(request: Request):
    caller_number, called_number, form_data = await call_info(request)
    service = get_job_info(caller_number, "service")

    with new_response() as response:
        say(response, "Hello!")
        agent_message(caller_number, "Hello!")
        response.redirect(f"{settings.env.SERVER_URL}/next-step")
        return send_request(request, response)
```

### TwiML Response Building

Use helpers from `twilio_agent/actions/twilio_actions.py`:
- `new_response()` - Context manager for TwiML responses
- `say(response, text)` - Add speech output (uses ElevenLabs TTS)
- `gather(response, **kwargs)` - Collect user input
- `send_request(request, response)` - Send TwiML with proper headers

### Service Context

Always determine which service is handling the call:
```python
service = which_service(called_number)  # Returns service_id
announcements = settings.service(service).announcements
```

## Dashboard API

RESTful API in `twilio_agent/api/dashboard.py`:

**Locations:** `GET/POST/PUT/DELETE /api/dashboard/services/{service_id}/locations`

**Settings:** `GET/PUT /api/dashboard/services/{service_id}/settings/{setting_type}`
- `setting_type`: phone-number, emergency-contact, direct-forwarding, active-hours, pricing, announcements

**Calls:** `GET /api/dashboard/calls` - List all calls with metadata

**Call Detail:** `GET /api/dashboard/calls/{number}/{timestamp}` - Get full call details including messages and recordings

**Recordings:** `GET /api/dashboard/calls/{number}/{timestamp}/recording/{recording_type}` - Download call recording (supports range requests)

All dashboard endpoints require authentication via `require_auth` dependency.

## Webhooks

Configure these in Twilio Console:
- **Voice URL:** `https://your-domain.com/incoming-call`
- **SMS URL:** `https://your-domain.com/webhook/sms`
- **Status Callback:** `https://your-domain.com/status-change`

## Environment Variables

Required in `.env` file:
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`
- `TELEGRAM_CHAT_ID` - Shared chat ID for all services
- `TELEGRAM_BOT_TOKEN_SCHLUESSEL_ALLGAEU` - Bot token for schluessel-allgaeu service
- `TELEGRAM_BOT_TOKEN_NOTDIENST_SCHLUESSEL` - Bot token for notdienst-schluessel service
- `TELEGRAM_BOT_TOKEN_NOTDIENST_ABSCHLEPP` - Bot token for notdienst-abschlepp service
- `MAPS_API_KEY` - Google Maps for geocoding
- `REDIS_URL` - Redis connection string
- `ELEVENLABS_API_KEY` - Text-to-speech and speech-to-text
- `XAI_API_KEY` - Primary LLM provider
- `SERVER_URL` - Base URL for webhooks (e.g., https://your-domain.com)
- `DASHBOARD_URL` - Dashboard frontend URL
- `DOMAIN` - Domain name (production)

Optional:
- `BASETEN_API_KEY` - Alternative LLM
- `DEBUG=true` - Enable debug mode
- `TELEGRAM_BOT_TOKEN` - Legacy fallback bot token

See `TELEGRAM_SETUP.md` for detailed Telegram bot configuration instructions.

## Testing

Tests mirror the source structure in `tests/` directory.

Key test files:
- `tests/twilio_agent/utils/test_contacts.py` - Contact management
- `tests/twilio_agent/utils/test_ai.py` - AI utilities

When writing tests:
- Use `pytest-asyncio` for async handlers
- Mock Redis and external APIs (Twilio, Telegram, Google Maps, ElevenLabs)
- Test both success and error paths
- Validate TwiML output structure
