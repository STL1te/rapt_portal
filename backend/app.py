"""FastAPI app: serves cached RAPT data from the local DB, runs a background sync."""

import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import SYNC_INTERVAL_SECONDS
from db import init_db
from routers import ai, brewzillas, hydrometers, system, yeasts
from system_jobs import ensure_interval_base_sync


async def _sync_loop() -> None:
    while True:
        try:
            await ensure_interval_base_sync()
        except Exception as e:  # noqa: BLE001
            print(f"sync error: {e}", flush=True)
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(finalize_stale=True)
    task = asyncio.create_task(_sync_loop())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="RAPT Portal", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system.router)
app.include_router(hydrometers.router)
app.include_router(brewzillas.router)
app.include_router(yeasts.router)
app.include_router(ai.router)
