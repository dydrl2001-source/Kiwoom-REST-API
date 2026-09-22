import os, asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
import psycopg
from telethon import TelegramClient, events
from telethon.tl.types import Channel

API_ID=int(os.getenv("TELEGRAM_API_ID","0") or 0)
API_HASH=os.getenv("TELEGRAM_API_HASH","")
DB=os.getenv("DATABASE_URL","")
SESSION_PATH=os.getenv("TELEGRAM_SESSION_PATH","/data/marketcollector")
BACKFILL_DAYS=int(os.getenv("TELEGRAM_BACKFILL_DAYS","7"))
RECONCILE_SECONDS=int(os.getenv("TELEGRAM_RECONCILE_SECONDS","600"))

def db(): return psycopg.connect(DB)

def ensure_schema():
    with db() as c, c.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS telegram_messages(
          id BIGSERIAL PRIMARY KEY,collected_at TIMESTAMPTZ NOT NULL,message_date TIMESTAMPTZ,
          channel_id BIGINT NOT NULL,channel_name TEXT,username TEXT,message_id BIGINT NOT NULL,text TEXT,
          message_url TEXT,has_media INTEGER DEFAULT 0,UNIQUE(channel_id,message_id)
        );
        CREATE TABLE IF NOT EXISTS telegram_channel_state(
          channel_id BIGINT PRIMARY KEY,channel_name TEXT,username TEXT,last_message_id BIGINT,updated_at TIMESTAMPTZ NOT NULL
        );
        """); c.commit()

def save(chat,msg):
    username=getattr(chat,"username",None) or ""
    url=f"https://t.me/{username}/{msg.id}" if username else ""
    with db() as c, c.cursor() as cur:
        cur.execute("""INSERT INTO telegram_messages(collected_at,message_date,channel_id,channel_name,username,message_id,text,message_url,has_media)
                       VALUES(now(),%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(channel_id,message_id) DO NOTHING""",
                    (msg.date,int(chat.id),getattr(chat,"title",""),username,msg.id,msg.message or "",url,1 if msg.media else 0))
        cur.execute("""INSERT INTO telegram_channel_state(channel_id,channel_name,username,last_message_id,updated_at)
                       VALUES(%s,%s,%s,%s,now()) ON CONFLICT(channel_id) DO UPDATE SET channel_name=excluded.channel_name,
                       username=excluded.username,last_message_id=GREATEST(COALESCE(telegram_channel_state.last_message_id,0),excluded.last_message_id),updated_at=now()""",
                    (int(chat.id),getattr(chat,"title",""),username,msg.id))
        c.commit()

async def backfill(client):
    cutoff=datetime.now(timezone.utc)-timedelta(days=BACKFILL_DAYS)
    async for dialog in client.iter_dialogs():
        ent=dialog.entity
        if not isinstance(ent,Channel) or not getattr(ent,"broadcast",False): continue
        async for msg in client.iter_messages(ent,limit=10000):
            if not msg.date or msg.date<cutoff: break
            save(ent,msg)

async def reconcile(client):
    while True:
        try: await backfill(client)
        except Exception as e: print("reconcile error",e,flush=True)
        await asyncio.sleep(RECONCILE_SECONDS)

async def main():
    if not API_ID or not API_HASH: raise SystemExit("TELEGRAM_API_ID/HASH missing")
    ensure_schema()
    client=TelegramClient(SESSION_PATH,API_ID,API_HASH)
    if not Path(SESSION_PATH+".session").exists():
        raise SystemExit("Telegram session missing. Run telegram_login service first.")
    await client.connect()
    if not await client.is_user_authorized():
        raise SystemExit("Telegram session is not authorized. Run telegram_login service first.")
    @client.on(events.NewMessage)
    async def handler(event):
        chat=await event.get_chat()
        if isinstance(chat,Channel) and getattr(chat,"broadcast",False):
            save(chat,event.message)
    asyncio.create_task(reconcile(client))
    print("Telegram collector started",flush=True)
    await client.run_until_disconnected()

if __name__=="__main__": asyncio.run(main())
