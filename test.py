import asyncio
import logging
import os
import time
from contextlib import contextmanager

import dotenv
from fastapi import Request
from fastapi.responses import HTMLResponse
from twilio.rest import Client
from twilio.twiml.voice_response import (Connect, Dial, Gather, Number,
                                         VoiceResponse)

dotenv.load_dotenv()


# Find your Account SID and Auth Token at twilio.com/console
# and set the environment variables. See http://twil.io/secure
account_sid = os.environ["TWILIO_ACCOUNT_SID"]
auth_token = os.environ["TWILIO_AUTH_TOKEN"]
client = Client(account_sid, auth_token)

outgoing_caller_ids = client.outgoing_caller_ids.list(limit=20)

for record in outgoing_caller_ids:
    print(record.sid)