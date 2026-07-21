"""ORM row -> dict serializers shared by the API routers."""
import json
import statistics

from sqlalchemy import select

from db import BrewSession, HydrometerSession, HydrometerTelemetry

_GRAVITY_MIN, _GRAVITY_MAX = 980.0, 1130.0


def row(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def _current_gravity(db, session_id: str) -> float | None:
    readings = [
        x for x in db.scalars(
            select(HydrometerTelemetry.gravity)
            .where(HydrometerTelemetry.session_id == session_id)
            .order_by(HydrometerTelemetry.timestamp)
        )
        if x is not None and _GRAVITY_MIN <= x <= _GRAVITY_MAX
    ]
    if not readings:
        return None
    tail = readings[-max(5, len(readings) // 20):]
    return round(statistics.median(tail), 2)


def session_dict(s: HydrometerSession, db=None) -> dict:
    """Session row plus derived ABV and apparent attenuation (OG/FG in points)."""
    d = row(s)
    og, fg = s.original_gravity, s.final_gravity
    ok = og is not None and fg is not None and og >= fg
    d["current_gravity"] = _current_gravity(db, s.id) if db is not None else None
    d["abv"] = round((og - fg) / 7.5, 2) if ok else None
    d["attenuation"] = round((og - fg) / (og - 1000) * 100, 1) if ok and og > 1000 else None
    return d


def brew_session_dict(s: BrewSession) -> dict:
    """Brew session row with the embedded profile (steps/alerts) parsed from JSON."""
    d = row(s)
    d.pop("profile_json", None)
    d["profile"] = json.loads(s.profile_json) if s.profile_json else None
    return d
