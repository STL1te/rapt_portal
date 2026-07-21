"""Hydrometer (RAPT Pill) devices, sessions and telemetry."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from db import Hydrometer, HydrometerSession, HydrometerTelemetry, SessionLocal
from serializers import row, session_dict

router = APIRouter()


@router.get("/api/hydrometers")
def list_hydrometers() -> list[dict]:
    with SessionLocal() as db:
        return [row(h) for h in db.scalars(select(Hydrometer))]


@router.get("/api/hydrometers/{hydrometer_id}/sessions")
def list_sessions(hydrometer_id: str) -> list[dict]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(HydrometerSession)
            .where(HydrometerSession.hydrometer_id == hydrometer_id)
            .order_by(HydrometerSession.start_date.desc())
        )
        return [session_dict(s, db) for s in rows]


@router.get("/api/hydrometer-sessions/{session_id}")
def get_session(session_id: str) -> dict:
    with SessionLocal() as db:
        s = db.get(HydrometerSession, session_id)
        if not s:
            raise HTTPException(404, "session not found")
        return session_dict(s, db)


@router.get("/api/hydrometer-sessions/{session_id}/telemetry")
def session_telemetry(
    session_id: str, start: str | None = None, end: str | None = None
) -> list[dict]:
    with SessionLocal() as db:
        if not db.get(HydrometerSession, session_id):
            raise HTTPException(404, "session not found")
        q = select(HydrometerTelemetry).where(HydrometerTelemetry.session_id == session_id)
        if start:
            q = q.where(HydrometerTelemetry.timestamp >= start)
        if end:
            q = q.where(HydrometerTelemetry.timestamp <= end)
        rows = db.scalars(q.order_by(HydrometerTelemetry.timestamp))
        return [row(t) for t in rows]
