import os
import asyncio
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession
from pathlib import Path

load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

API_ID = os.getenv("TG_API_ID", "").strip()
API_HASH = os.getenv("TG_API_HASH", "").strip()

if not API_ID or not API_HASH:
    raise SystemExit("Set TG_API_ID and TG_API_HASH in .env")

async def main():
    async with TelegramClient(StringSession(), int(API_ID), API_HASH) as client:
        print("\nString session (save this as TG_STRING_SESSION):")
        print(client.session.save())

if __name__ == "__main__":
    asyncio.run(main())
