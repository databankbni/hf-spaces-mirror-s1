"""Standalone, read-only Telegram diagnostic probe.

This file is not imported or called by any bot component. It reads the existing
API_ID, API_HASH, SESSION_STRING, and BOT_TOKEN environment variables without
printing their values.

The clients are created in memory, so this probe does not create or modify a
local Pyrogram session file. It does not send, delete, edit, or forward
messages, and it does not join or leave any chat.
"""

import asyncio
import logging
import os
from typing import Optional

from pyrogram import Client


CHANNEL_ID = -1001210871112

# Suppress library logs so stdout contains only diagnostic output.
logging.basicConfig(level=logging.CRITICAL)
for logger_name in ("pyrogram", "pyrogram.session", "pyrogram.client"):
    logging.getLogger(logger_name).setLevel(logging.CRITICAL)


def safe_error(error: Exception, secrets: tuple[str, ...]) -> str:
    """Return complete exception text while redacting known secret values."""
    text = f"{type(error).__name__}: {error}"
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text


async def main() -> None:
    api_id_text = os.environ.get("API_ID")
    api_hash = os.environ.get("API_HASH")
    session_string = os.environ.get("SESSION_STRING")
    bot_token = os.environ.get("BOT_TOKEN")

    missing = [
        name
        for name, value in (
            ("API_ID", api_id_text),
            ("API_HASH", api_hash),
            ("SESSION_STRING", session_string),
            ("BOT_TOKEN", bot_token),
        )
        if not value
    ]
    if missing:
        print("CONFIG_FAIL")
        print("missing_variables=" + ",".join(missing))
        return

    try:
        api_id = int(api_id_text)
    except ValueError as error:
        print("CONFIG_FAIL")
        print("API_ID must be an integer")
        print(safe_error(error, (api_hash, session_string, bot_token)))
        return

    secrets = (api_hash, session_string, bot_token)
    user_client: Optional[Client] = None
    bot_client: Optional[Client] = None

    try:
        user_client = Client(
            "runtime_probe_user",
            api_id=api_id,
            api_hash=api_hash,
            session_string=session_string,
            in_memory=True,
        )
        bot_client = Client(
            "runtime_probe_bot",
            api_id=api_id,
            api_hash=api_hash,
            bot_token=bot_token,
            in_memory=True,
        )

        await user_client.start()

        try:
            me = await user_client.get_me()
            print("USER_ME_OK")
            print(f"user_id={me.id}")
            print(f"username={me.username}")
        except Exception as error:
            print("USER_ME_FAIL")
            print(safe_error(error, secrets))

        try:
            chat = await user_client.get_chat(CHANNEL_ID)
            print("USER_GET_CHAT_OK")
            print(f"chat_id={chat.id}")
            print(f"title={chat.title}")
            print(f"username={chat.username}")
            print(f"type={chat.type}")
        except Exception as error:
            print("USER_GET_CHAT_FAIL")
            print(safe_error(error, secrets))

        try:
            messages = [
                message
                async for message in user_client.get_chat_history(
                    CHANNEL_ID,
                    limit=1,
                )
            ]
            if messages:
                print("USER_HISTORY_OK")
                print(f"latest_message_id={messages[0].id}")
            else:
                print("USER_HISTORY_FAIL")
                print("No message was returned")
        except Exception as error:
            print("USER_HISTORY_FAIL")
            print(safe_error(error, secrets))

        try:
            dialog_found = False
            async for dialog in user_client.get_dialogs():
                if dialog.chat and dialog.chat.id == CHANNEL_ID:
                    dialog_found = True
                    print("USER_DIALOG_FOUND")
                    print(f"id={dialog.chat.id}")
                    print(f"title={dialog.chat.title}")
                    break
            if not dialog_found:
                print("USER_DIALOG_NOT_FOUND")
        except Exception as error:
            print("USER_DIALOG_NOT_FOUND")
            print(safe_error(error, secrets))

        await bot_client.start()

        try:
            chat = await bot_client.get_chat(CHANNEL_ID)
            print("BOT_GET_CHAT_OK")
            print(f"chat_id={chat.id}")
            print(f"title={chat.title}")
            print(f"username={chat.username}")
            print(f"type={chat.type}")
        except Exception as error:
            print("BOT_GET_CHAT_FAIL")
            print(safe_error(error, secrets))

    finally:
        if bot_client is not None:
            try:
                if bot_client.is_connected:
                    await bot_client.stop()
            except Exception:
                pass
        if user_client is not None:
            try:
                if user_client.is_connected:
                    await user_client.stop()
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(main())

