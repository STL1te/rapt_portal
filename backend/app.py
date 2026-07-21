"""FastAPI app: serves cached RAPT data from the local DB, runs a background sync."""
import asyncio
import contextlib
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

import sync
from config import SYNC_INTERVAL_SECONDS
from db import Hydrometer, Session, SessionLocal, Telemetry, init_db


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


def _row(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def _session_dict(s: Session) -> dict:
    """Session row plus derived ABV and apparent attenuation (OG/FG in points)."""
    d = _row(s)
    og, fg = s.original_gravity, s.final_gravity
    ok = og is not None and fg is not None and og >= fg
    d["abv"] = round((og - fg) / 7.5, 2) if ok else None
    d["attenuation"] = round((og - fg) / (og - 1000) * 100, 1) if ok and og > 1000 else None
    return d


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/sync")
async def trigger_sync() -> dict:
    return await sync.sync_once()


@app.get("/api/hydrometers")
def list_hydrometers() -> list[dict]:
    with SessionLocal() as db:
        return [_row(h) for h in db.scalars(select(Hydrometer))]


@app.get("/api/hydrometers/{hydrometer_id}/sessions")
def list_sessions(hydrometer_id: str) -> list[dict]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(Session)
            .where(Session.hydrometer_id == hydrometer_id)
            .order_by(Session.start_date.desc())
        )
        return [_session_dict(s) for s in rows]


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    with SessionLocal() as db:
        s = db.get(Session, session_id)
        if not s:
            raise HTTPException(404, "session not found")
        return _session_dict(s)


@app.get("/api/sessions/{session_id}/telemetry")
def session_telemetry(
    session_id: str, start: str | None = None, end: str | None = None
) -> list[dict]:
    with SessionLocal() as db:
        if not db.get(Session, session_id):
            raise HTTPException(404, "session not found")
        q = select(Telemetry).where(Telemetry.session_id == session_id)
        if start:
            q = q.where(Telemetry.timestamp >= start)
        if end:
            q = q.where(Telemetry.timestamp <= end)
        rows = db.scalars(q.order_by(Telemetry.timestamp))
        return [_row(t) for t in rows]
