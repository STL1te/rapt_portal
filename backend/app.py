"""FastAPI app: serves cached RAPT data from the local DB, runs a background sync."""
import asyncio
import contextlib
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import sync
from config import SYNC_INTERVAL_SECONDS
from db import init_db
from routers import brewzillas, hydrometers, system, yeasts


async def _sync_loop() -> None:
    while True:
        try:
            r = await sync.sync_once()
            ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
            print(f"[{ts}] synced {r['hydrometers']} hydrometers, "
                  f"{r['active_sessions']} active session(s)", flush=True)
        except Exception as e:  # noqa: BLE001 — never let the loop die
            print(f"sync error: {e}", flush=True)
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task = asyncio.create_task(_sync_loop())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="RAPT Portal", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system.router)
app.include_router(hydrometers.router)
app.include_router(brewzillas.router)
app.include_router(yeasts.router)
