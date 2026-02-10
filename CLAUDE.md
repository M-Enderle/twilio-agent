# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

German-language AI voice/SMS dispatcher for emergency services (locksmith "Schlüsseldienst" and towing "Abschleppdienst"). Built with FastAPI, it handles Twilio voice webhooks, classifies caller intent via LLM, collects addresses, calculates pricing by distance, and routes calls to the nearest available service provider.

## Commands

```bash
# Install dependencies
poetry install

# Run dev server (requires Redis running)
uvicorn twilio_agent.conversation_flow:app --reload

# Start Redis for local dev
docker-compose up -d redis

# Format code
poetry run black twilio_agent/
poetry run isort twilio_agent/

# Run tests
poetry run pytest

# Docker (production)
docker-compose -f docker-compose.prod.yml up -d
```

## Architecture

**Entry point:** `twilio_agent/conversation_flow.py` — creates the FastAPI app, registers all routers, serves cached audio files.

**`twilio_agent/flow/`** — Modular call conversation steps, each an async FastAPI endpoint:
- `call_entry.py`: `/incoming-call` greeting, intent classification (locksmith vs towing)
- `address.py`: Address collection via voice recording, transcription, geocoding validation
- `sms_and_transfer.py`: SMS fallback for location sharing, cost confirmation
- `management.py`: Contact queue management, call transfer routing, status tracking
- `shared.py`: Shared helpers (narration, transfer initiation, error handling)

**`twilio_agent/actions/`** — External service integrations (Twilio TwiML, Redis state, Telegram notifications, call recording, location sharing).

**`twilio_agent/utils/`** — Core utilities:
- `ai.py`: Dual LLM orchestration — primary: XAI Grok (`grok-4-fast-non-reasoning`), fallback: Baseten GPT-OSS-120B (if Grok times out >1s). Results are cached.
- `cache.py`: Multi-level caching (in-memory dict + disk JSON/binary) for LLM results and audio
- `contacts.py`: Loads service provider contacts from `handwerker.yaml`
- `eleven.py`: ElevenLabs TTS (German voice) and ASR (`de-DE`)
- `location_utils.py`: Google Maps geocoding with postal code extraction
- `pricing.py`: Distance-based cost calculation using Google Maps routing API

## Key Patterns

**TwiML Response Pattern:** Flow endpoints build Twilio TwiML responses using `new_response()` context manager, add narration/actions, then return via `send_request()`.

**Redis Key Convention:** `notdienststation:anrufe:{phone}:{key}` for session state, `notdienststation:verlauf:{number}:{timestamp}:{type}` for message history.

**All handlers are async.** LLM calls run in thread pools via `asyncio.to_thread()`. Parallel external calls use `asyncio.gather()`.

**All user-facing text and TTS is in German.**

## Key Config Files

- `handwerker.yaml`: Service provider contacts (name, phone, address, zipcode, fallback flag) organized by category (locksmith/towing)
- `.env`: API keys for Twilio, XAI, Google Maps, ElevenLabs, Baseten, Telegram; Redis URL; domain config
- `templates/`: Jinja2 HTML templates for location sharing UI
