"""ORM row -> dict serializers shared by the API routers."""

import json
import statistics

from sqlalchemy import select
from sqlalchemy.orm import object_session

from db import BrewSession, BrewTelemetry, HydrometerSession, HydrometerTelemetry, Yeast

_GRAVITY_MIN, _GRAVITY_MAX = 980.0, 1130.0


def row(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


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


def brew_session_dict(s: BrewSession) -> dict:
    """Brew session row with the embedded profile (steps/alerts) parsed from JSON."""
    d = row(s)
    d.pop("profile_json", None)
    profile = json.loads(s.profile_json) if s.profile_json else None
    d["profile"] = profile

    steps = sorted((profile or {}).get("steps") or [], key=lambda step: step.get("order") or 0)
    step_by_id = {step.get("id"): step for step in steps if step.get("id")}
    session = object_session(s)
    latest = (
        session.scalar(
            select(BrewTelemetry)
            .where(BrewTelemetry.session_id == s.id)
            .order_by(BrewTelemetry.timestamp.desc())
        )
        if session is not None
        else None
    )
    current_step = step_by_id.get(latest.profile_step_id) if latest else None
    current_step_order = current_step.get("order") if current_step else None
    current_step_progress = latest.profile_step_progress if latest else None
    if current_step_progress is not None:
        current_step_progress = max(0.0, min(float(current_step_progress), 1.0))

    total_steps = len(steps)
    completed_steps = 0
    if current_step_order is not None:
        completed_steps = len(
            [step for step in steps if (step.get("order") or 0) < current_step_order]
        )
    elif not s.active and total_steps:
        completed_steps = total_steps
    d["current_step_id"] = latest.profile_step_id if latest else None
    d["current_step_name"] = current_step.get("name") if current_step else None
    d["current_step_order"] = current_step_order
    d["current_step_progress"] = current_step_progress
    d["session_progress"] = (
        round((completed_steps + (current_step_progress or 0.0)) / total_steps, 3)
        if total_steps
        else None
    )
    d["total_steps"] = total_steps
    d["last_telemetry_at"] = latest.timestamp if latest else None
    d["latest_temperature"] = latest.temperature if latest else None
    d["latest_target_temperature"] = latest.target_temperature if latest else None
    d["latest_min_target_temperature"] = latest.min_target_temperature if latest else None
    d["latest_max_target_temperature"] = latest.max_target_temperature if latest else None
    d["latest_wort_temperature"] = latest.control_device_temperature if latest else None
    d["latest_heating_run_time"] = latest.heating_run_time if latest else None
    d["latest_aux_run_time"] = latest.auxillary_run_time if latest else None
    d["delta_to_target"] = (
        round(latest.temperature - latest.target_temperature, 1)
        if latest and latest.temperature is not None and latest.target_temperature is not None
        else None
    )
    d["wort_delta_to_target"] = (
        round(latest.control_device_temperature - latest.target_temperature, 1)
        if latest
        and latest.control_device_temperature not in (None, 0)
        and latest.target_temperature is not None
        else None
    )
    d["step_target_temperature"] = current_step.get("temperature") if current_step else None
    return d
