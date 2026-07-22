"""FastAPI app: serves cached RAPT data from the local DB, runs a background sync."""

import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import SYNC_INTERVAL_SECONDS
from core.db import init_db
from features.ai.router import router as ai_router
from features.brewzillas.router import router as brewzillas_router
from features.hydrometers.router import router as hydrometers_router
from features.system.router import router as system_router
from features.system.services import ensure_interval_base_sync
from features.yeasts.router import router as yeasts_router


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

app.include_router(system_router)
app.include_router(hydrometers_router)
app.include_router(brewzillas_router)
app.include_router(yeasts_router)
app.include_router(ai_router)
