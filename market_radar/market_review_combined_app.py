"""Single-service Railway entrypoint for review journal + read-only bridge.

Runs the append-only 08:20/09:20 journal capture loop as a background task
inside the same FastAPI process that serves the read-only review API. This
exists to fit constrained Railway plans without adding a second service.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI

import market_review_journal as journal
from market_review_bridge_app import app as bridge_app


async def journal_loop():
    # Schema creation is the only DB write outside issued decision inserts.
    await asyncio.to_thread(journal.ensure_schema)
    while True:
        try:
            await asyncio.to_thread(journal.run_once, datetime.now(timezone.utc))
        except Exception as exc:
            # Never log payloads, credentials or DB bodies.
            print("MARKET_REVIEW_COMBINED: JOURNAL_ERROR", type(exc).__name__, flush=True)
        await asyncio.sleep(journal.POLL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task=asyncio.create_task(journal_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app=bridge_app
app.router.lifespan_context=lifespan
