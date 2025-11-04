"""Shared helpers that keep the call flow modules tidy and consistent."""

from __future__ import annotations

from typing import Iterable

from fastapi import Request

from twilio_agent.actions.redis_actions import agent_message
from twilio_agent.actions.twilio_actions import (caller, fallback_no_response,
                                                 new_response, say,
                                                 send_request, start_transfer)


async def get_caller_number(request: Request) -> str:
    """Return the caller phone number extracted from the current request."""
    return await caller(request)


def narrate(response, caller_number: str, message: str) -> None:
    """Send a message to the caller and mirror it to the agent timeline."""
    say(response, message)
    agent_message(caller_number, message)


async def send_twilio_response(
    request: Request,
    response,
    *,
    include_fallback: bool = True,
):
    """Render the current Twilio response and optionally add the generic fallback."""
    if include_fallback:
        await fallback_no_response(response, request)
    return send_request(request, response)


async def transfer_with_message(
    request: Request,
    message: str = "Ich verbinde dich mit einem Mitarbeiter.",
):
    """Utility to announce a transfer and trigger the Twilio transfer flow."""
    caller_number = await get_caller_number(request)
    with new_response() as response:
        narrate(response, caller_number, message)
        start_transfer(response, caller_number)
        return send_request(request, response)


def append_actions(response, actions: Iterable) -> None:
    """Append Twilio actions (Gather, Record, …) to the response in order."""
    for action in actions:
        response.append(action)
