"""BrewZilla devices, brew sessions and telemetry."""
from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from db import BrewSession, BrewTelemetry, BrewZilla, SessionLocal
from serializers import brew_session_dict, row

router = APIRouter()


@router.get("/api/brewzillas")
def list_brewzillas() -> list[dict]:
    with SessionLocal() as db:
        return [row(b) for b in db.scalars(select(BrewZilla))]


@router.get("/api/brewzillas/{brewzilla_id}/sessions")
def list_brew_sessions(brewzilla_id: str) -> list[dict]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(BrewSession)
            .where(BrewSession.brewzilla_id == brewzilla_id)
            .order_by(BrewSession.start_date.desc())
        )
        # list view doesn't need the full profile payload
        return [{k: v for k, v in brew_session_dict(s).items() if k != "profile"} for s in rows]


@router.get("/api/brew-sessions/{session_id}")
def get_brew_session(session_id: str) -> dict:
    with SessionLocal() as db:
        s = db.get(BrewSession, session_id)
        if not s:
            raise HTTPException(404, "brew session not found")
        return brew_session_dict(s)


@router.get("/api/brew-sessions/{session_id}/telemetry")
def brew_session_telemetry(
    session_id: str, start: str | None = None, end: str | None = None
) -> list[dict]:
    with SessionLocal() as db:
        if not db.get(BrewSession, session_id):
            raise HTTPException(404, "brew session not found")
        q = select(BrewTelemetry).where(BrewTelemetry.session_id == session_id)
        if start:
            q = q.where(BrewTelemetry.timestamp >= start)
        if end:
            q = q.where(BrewTelemetry.timestamp <= end)
        rows = db.scalars(q.order_by(BrewTelemetry.timestamp))
        return [row(t) for t in rows]
