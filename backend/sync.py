"""Pull RAPT data into the local DB.

RAPT exposes only the *active* profile session per hydrometer — no history,
no end date, no OG/FG. So the local DB *is* the session history: we record
each active session as we see it, close it when it changes/disappears, and
derive OG/FG from the first/last telemetry point.
"""
from datetime import datetime, timezone

from sqlalchemy import func, select

import rapt_client
from db import (
    BrewSession,
    BrewTelemetry,
    BrewZilla,
    Hydrometer,
    HydrometerSession,
    HydrometerTelemetry,
    SessionLocal,
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _dt(value) -> datetime | None:
    """Parse to naive UTC — SQLite stores naive, so keep everything naive to
    make timestamp equality (dedup) and range filters consistent."""
    if not value:
        return None
    if isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(value, timezone.utc)
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _upsert(db, model, row: dict) -> None:
    obj = db.get(model, row["id"])
    if obj is None:
        db.add(model(**row))
    else:
        for k, v in row.items():
            setattr(obj, k, v)


async def sync_once() -> dict:
    hydrometers = await rapt_client.get_hydrometers()
    active_pairs: list[tuple[str, str]] = []  # (hydrometer_id, session_id)

    with SessionLocal() as db:
        for h in hydrometers:
            hid = h.get("id")
            if not hid:
                continue
            active = h.get("activeProfileSession") or None
            active_id = (active or {}).get("id")

            # close a session that just ended (active changed or went away)
            prev = db.get(Hydrometer, hid)
            prev_id = prev.active_session_id if prev else None
            if prev_id and prev_id != active_id:
                _close_session(db, prev_id)

            _upsert(db, Hydrometer, {
                "id": hid,
                "name": h.get("name"),
                "gravity": h.get("gravity"),
                "temperature": h.get("temperature"),
                "battery": h.get("battery"),
                "rssi": h.get("rssi"),
                "active_session_id": active_id,
                "updated_at": _now(),
            })

            if active_id:
                _upsert(db, HydrometerSession, {
                    "id": active_id,
                    "hydrometer_id": hid,
                    "name": active.get("name"),
                    "start_date": _dt(active.get("startDate")),
                    "active": True,
                })
                active_pairs.append((hid, active_id))
        db.commit()

    for hid, sid in active_pairs:
        await _sync_telemetry(hid, sid)
        _refresh_gravities(sid)

    brew = await _sync_brewzillas()

    return {
        "hydrometers": len(hydrometers),
        "active_sessions": len(active_pairs),
        "brewzillas": brew["devices"],
        "brew_active": brew["active"],
    }


async def _sync_brewzillas() -> dict:
    import json

    devices = await rapt_client.get_brewzillas()
    active_pairs: list[tuple[str, str]] = []

    with SessionLocal() as db:
        for b in devices:
            bid = b.get("id")
            if not bid:
                continue
            active = b.get("activeProfileSession") or None
            active_id = (active or {}).get("id")

            prev = db.get(BrewZilla, bid)
            prev_id = prev.active_session_id if prev else None
            if prev_id and prev_id != active_id:
                s = db.get(BrewSession, prev_id)
                if s and s.active:
                    s.active = False
                    s.end_date = _now()

            _upsert(db, BrewZilla, {
                "id": bid,
                "name": b.get("name"),
                "temperature": b.get("temperature"),
                "target_temperature": b.get("targetTemperature"),
                "heating_enabled": b.get("heatingEnabled"),
                "heating_utilisation": b.get("heatingUtilisation"),
                "pump_enabled": b.get("pumpEnabled"),
                "pump_utilisation": b.get("pumpUtilisation"),
                "rssi": b.get("rssi"),
                "active_session_id": active_id,
                "updated_at": _now(),
            })

            if active_id:
                prof = active.get("profile")
                _upsert(db, BrewSession, {
                    "id": active_id,
                    "brewzilla_id": bid,
                    "name": active.get("name") or (prof or {}).get("name"),
                    "profile_id": active.get("profileId"),
                    "profile_json": json.dumps(prof, ensure_ascii=False) if prof else None,
                    "start_date": _dt(active.get("startDate")),
                    "active": True,
                })
                active_pairs.append((bid, active_id))
        db.commit()

    for bid, sid in active_pairs:
        await _sync_brew_telemetry(bid, sid)

    return {"devices": len(devices), "active": len(active_pairs)}


async def _sync_brew_telemetry(brewzilla_id: str, session_id: str) -> None:
    with SessionLocal() as db:
        last = db.scalar(
            select(func.max(BrewTelemetry.timestamp)).where(BrewTelemetry.session_id == session_id)
        )
        existing = set(
            db.scalars(select(BrewTelemetry.timestamp).where(BrewTelemetry.session_id == session_id))
        )

    start = last.isoformat() if last else None
    points = await rapt_client.get_brewzilla_telemetry(brewzilla_id, start=start, session_id=session_id)

    with SessionLocal() as db:
        for p in points or []:
            ts = _dt(p.get("createdOn"))
            if ts is None or ts in existing:
                continue
            db.add(BrewTelemetry(
                session_id=session_id,
                timestamp=ts,
                temperature=p.get("temperature"),
                target_temperature=p.get("targetTemperature"),
                min_target_temperature=p.get("minTargetTemperature"),
                max_target_temperature=p.get("maxTargetTemperature"),
                control_device_temperature=p.get("controlDeviceTemperature"),
                heating_run_time=p.get("heatingRunTime"),
                heating_starts=p.get("heatingStarts"),
                auxillary_run_time=p.get("auxillaryRunTime"),
                auxillary_starts=p.get("auxillaryStarts"),
                profile_step_id=p.get("profileStepId"),
                profile_step_progress=p.get("profileStepProgress"),
                profile_session_time=p.get("profileSessionTime"),
                rssi=p.get("rssi"),
            ))
            existing.add(ts)
        db.commit()


def _close_session(db, session_id: str) -> None:
    s = db.get(HydrometerSession, session_id)
    if s and s.active:
        s.active = False
        s.end_date = _now()


async def _sync_telemetry(hydrometer_id: str, session_id: str) -> None:
    """Append only telemetry points newer than the last stored one."""
    with SessionLocal() as db:
        last = db.scalar(
            select(func.max(HydrometerTelemetry.timestamp))
            .where(HydrometerTelemetry.session_id == session_id)
        )
        existing = set(
            db.scalars(select(HydrometerTelemetry.timestamp)
                       .where(HydrometerTelemetry.session_id == session_id))
        )

    start = last.isoformat() if last else None
    points = await rapt_client.get_telemetry(hydrometer_id, start=start, session_id=session_id)

    with SessionLocal() as db:
        for p in points or []:
            ts = _dt(p.get("createdOn"))
            if ts is None or ts in existing:
                continue
            db.add(HydrometerTelemetry(
                session_id=session_id,
                timestamp=ts,
                gravity=p.get("gravity"),
                gravity_velocity=p.get("gravityVelocity"),
                temperature=p.get("temperature"),
                battery=p.get("battery"),
                rssi=p.get("rssi"),
            ))
            existing.add(ts)
        db.commit()


# plausible specific-gravity band (points); readings outside are Pill-out spikes
_GRAVITY_MIN, _GRAVITY_MAX = 980.0, 1130.0


def _refresh_gravities(session_id: str) -> None:
    """Estimate OG/FG from telemetry (the API doesn't provide them).

    Fermentation only lowers gravity, so FG must be <= OG. OG is the early
    plateau; FG is the late plateau — unless the Pill was lifted at the end and
    readings drift upward, in which case we fall back to the fermentation floor.
    Out-of-band spikes (Pill out of liquid) are discarded first.
    """
    import statistics

    with SessionLocal() as db:
        s = db.get(HydrometerSession, session_id)
        if not s:
            return
        g = [
            x for x in db.scalars(
                select(HydrometerTelemetry.gravity)
                .where(HydrometerTelemetry.session_id == session_id)
                .order_by(HydrometerTelemetry.timestamp)
            )
            if x is not None and _GRAVITY_MIN <= x <= _GRAVITY_MAX
        ]
        if not g:
            db.commit()
            return
        s.original_gravity = round(_og(g), 2)
        s.final_gravity = round(_fg(g), 2)
        db.commit()


def _og(g: list[float]) -> float:
    """Early plateau."""
    import statistics
    n = max(5, len(g) // 20)  # ~5% window
    return statistics.median(g[:n])


def _fg(g: list[float]) -> float:
    """Late plateau, resisting end-of-session up-drift (Pill lifted).

    Fermentation only lowers gravity, so FG <= OG. Take the median of the
    last-third readings at or below OG; if the whole tail drifted above OG,
    fall back to the median of all below-OG readings (the completed plateau).
    """
    import statistics
    og = _og(g)
    tail = g[-max(5, len(g) // 3):]
    plateau = [x for x in tail if x <= og]
    if plateau:
        return statistics.median(plateau)
    below = [x for x in g if x <= og]
    return statistics.median(below) if below else og
