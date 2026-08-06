#!/usr/bin/env python3
"""Generate a Pyrogram session string for the forwarder bot.

Run this ONCE on your computer:
    pip install pyrogram
    python3 get_session.py

Then paste the SESSION_STRING into your HuggingFace Space Secrets.
"""

import os
from pyrogram import Client

API_ID = 6426614
API_HASH = "056b8c463e160604f53a38bfe65d0d0e"

print("=" * 55)
print("  Telegram Forwarder — Session String Generator")
print("=" * 55)
print()
print("You will be asked for your phone number and the")
print("verification code Telegram sends you.")
print()

with Client(":memory:", api_id=API_ID, api_hash=API_HASH) as app:
    session_string = app.export_session_string()
    print()
    print("=" * 55)
    print("  SUCCESS! Add this to your HF Space Secrets")
    print("  as SESSION_STRING:")
    print()
    print(session_string)
    print()
    print("=" * 55)
