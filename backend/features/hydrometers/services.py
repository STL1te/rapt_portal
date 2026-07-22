"""Hydrometer session serialization: derived ABV, attenuation and current gravity."""

import statistics

from sqlalchemy import select

from core.db import HydrometerSession, HydrometerTelemetry, Yeast
from core.serializers import row

_GRAVITY_MIN, _GRAVITY_MAX = 980.0, 1130.0


def _current_gravity(db, session_id: str) -> float | None:
    readings = [
        x
        for x in db.scalars(
            select(HydrometerTelemetry.gravity)
            .where(HydrometerTelemetry.session_id == session_id)
            .order_by(HydrometerTelemetry.timestamp)
        )
        if x is not None and _GRAVITY_MIN <= x <= _GRAVITY_MAX
    ]
    if not readings:
        return None
    tail = readings[-max(5, len(readings) // 20) :]
    return round(statistics.median(tail), 2)


def session_dict(s: HydrometerSession, db=None) -> dict:
    """Session row plus derived ABV and apparent attenuation (OG/FG in points)."""
    d = row(s)
    og, fg = s.original_gravity, s.final_gravity
    ok = og is not None and fg is not None and og >= fg
    yeast = db.get(Yeast, s.yeast_id) if db is not None and s.yeast_id else None
    d["current_gravity"] = _current_gravity(db, s.id) if db is not None else None
    d["abv"] = round((og - fg) / 7.5, 2) if ok else None
    d["attenuation"] = round((og - fg) / (og - 1000) * 100, 1) if ok and og > 1000 else None
    d["yeast_name"] = yeast.name if yeast else None
    d["yeast_product_id"] = yeast.product_id if yeast else None
    d["yeast_attenuation"] = yeast.attenuation if yeast else None
    d["yeast_min_temperature"] = yeast.min_temperature if yeast else None
    d["yeast_max_temperature"] = yeast.max_temperature if yeast else None
    d["target_final_gravity"] = (
        round(og - (og - 1000) * yeast.attenuation / 100, 2)
        if yeast and yeast.attenuation is not None and og is not None
        else None
    )
    return d
