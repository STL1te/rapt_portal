"""BrewZilla session serialization and session-boundary heuristics."""

import json
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import object_session

from core.db import BrewSession, BrewTelemetry
from core.serializers import row

_SHORT_BREW_SESSION = timedelta(hours=1)
_BREW_GAP_CUTOFF = timedelta(hours=4)


def is_short_brew_session(s: BrewSession) -> bool:
    if not s.start_date:
        return False
    end = s.end_date or s.start_date
    return end - s.start_date < _SHORT_BREW_SESSION


def effective_brew_end(db, s: BrewSession) -> datetime | None:
    rows = list(
        db.scalars(
            select(BrewTelemetry.timestamp)
            .where(BrewTelemetry.session_id == s.id)
            .order_by(BrewTelemetry.timestamp)
        )
    )
    if not rows:
        return s.end_date
    for prev, cur in zip(rows, rows[1:]):
        if cur - prev > _BREW_GAP_CUTOFF:
            return prev
    return rows[-1]


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
