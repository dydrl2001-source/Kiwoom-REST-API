import os, asyncio
from telethon import TelegramClient

API_ID=int(os.getenv("TELEGRAM_API_ID","0") or 0)
API_HASH=os.getenv("TELEGRAM_API_HASH","")
SESSION_PATH=os.getenv("TELEGRAM_SESSION_PATH","/data/marketcollector")

async def main():
    if not API_ID or not API_HASH: raise SystemExit("TELEGRAM_API_ID/HASH missing in .env")
    client=TelegramClient(SESSION_PATH,API_ID,API_HASH)
    await client.start()
    me=await client.get_me()
    print(f"Telegram login completed: {getattr(me,'first_name','')}")
    await client.disconnect()

asyncio.run(main())
