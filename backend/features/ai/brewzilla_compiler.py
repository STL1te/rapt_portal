"""Compile a BeerJSON recipe plus BrewZilla overrides into a BrewZilla profile.

Pure and deterministic: no LLM calls, no randomness, no config reads. All defaults are
named module constants; see docs/beerjson-migration-plan.md section 6 for the rules.
"""

import re
from typing import Literal

from features.profiles.router import ProfileIn

from .beerjson_models import MashStepType, RecipeModel
from .brewzilla_overrides import BrewZillaOverrides

MASH_OUT_TEMPERATURE_C = 78.0
MASH_OUT_DURATION_SECONDS = 600
SPARGE_TEMPERATURE_C = 78.0
BOIL_TEMPERATURE_C = 100.0
COOLING_TEMPERATURE_C = 20.0
MASH_IN_DELTA_C = 3.0
MASH_OUT_DETECT_MIN_C = 76.0
DEFAULT_MASH_IN_ALERT = "Add grain"

_MASH_OUT_NAME_RE = re.compile(r"mash[\s-]*out|мэш[\s-]*аут", re.IGNORECASE)
_SECONDS_PER_UNIT = {"sec": 1, "min": 60, "hr": 3600, "day": 86400, "week": 604800}


def to_celsius(temperature) -> float:
    if temperature.unit == "C":
        return temperature.value
    return (temperature.value - 32) * 5 / 9


def to_seconds(time) -> int:
    return round(time.value * _SECONDS_PER_UNIT[time.unit])


def format_amount(amount) -> str:
    return f"{amount.value:g} {amount.unit}"


def _eff(value, default):
    return default if value is None else value


def _alert(
    text: str,
    trigger: Literal["StepStart", "StepEnd", "Temperature", "Duration"],
    *,
    temperature: float | None = None,
    length: int | None = None,
) -> dict:
    return {
        "id": None,
        "alertText": text.strip(),
        "trigger": trigger,
        "operator": None,
        "temperature": temperature,
        "gravity": None,
        "length": length,
    }


def _step(
    name: str,
    temperature: float,
    *,
    end_type: Literal["Duration", "Temperature", "Manual"],
    duration_type: Literal["Temperature", "Manual"],
    length: int | None,
    heating: float | None,
    pid: bool | None,
    alerts: list[dict] | None = None,
) -> dict:
    return {
        "id": None,
        "name": name.strip(),
        "order": 0,
        "controlType": "Target",
        "endType": end_type,
        "durationType": duration_type,
        "operator": None,
        "length": length,
        "temperature": temperature,
        "minTemperature": None,
        "maxTemperature": None,
        "gravity": None,
        "pumpEnabled": None,
        "pumpUtilisation": None,
        "heatingUtilisation": heating,
        "pidEnabled": pid,
        "sensorDifferential": None,
        "alerts": alerts or [],
    }


def _rest_step(
    steps: list[dict],
    *,
    name: str,
    temperature_c: float,
    duration_seconds: int,
    heating: float | None,
    pid: bool,
    end_alerts: list[dict],
    previous_temperature: float,
    transition_heating: float | None,
) -> float:
    """Append one mash rest (or the mash-out rest) plus its optional ramp-up step."""
    separate_transition = (
        transition_heating is not None
        and heating is not None
        and transition_heating != heating
        and previous_temperature < temperature_c
    )
    if separate_transition:
        steps.append(
            _step(
                f"→ {temperature_c:g} °C",
                temperature_c,
                end_type="Temperature",
                duration_type="Temperature",
                length=None,
                heating=transition_heating,
                pid=False,
            )
        )
    steps.append(
        _step(
            name,
            temperature_c,
            end_type="Duration",
            duration_type="Temperature",
            length=duration_seconds,
            heating=heating,
            pid=pid,
            alerts=end_alerts,
        )
    )
    return temperature_c


def _looks_like_mash_out(rests: list[MashStepType]) -> bool:
    last = rests[-1]
    if last.name and _MASH_OUT_NAME_RE.search(last.name):
        return True
    return len(rests) >= 2 and to_celsius(last.step_temperature) >= MASH_OUT_DETECT_MIN_C


def compile_brewzilla_profile(
    recipe: RecipeModel, overrides: BrewZillaOverrides | None = None
) -> dict:
    """Compile a BeerJSON recipe plus BrewZilla overrides into a BrewZilla profile."""
    ov = overrides or BrewZillaOverrides()

    rests = list(recipe.mash.mash_steps) if recipe.mash else []

    # Recognized independently of include_mash_out: a rest the source wrote as the
    # mash-out must never fall through to the ordinary-rest loop below either way.
    recognized = rests.pop() if rests and _looks_like_mash_out(rests) else None

    mash_out_name = mash_out_temperature_c = mash_out_duration_seconds = None
    if _eff(ov.include_mash_out, True):
        if recognized is not None:
            mash_out_name = recognized.name or "Mash Out"
            mash_out_temperature_c = _eff(
                ov.mash_out_temperature_c, to_celsius(recognized.step_temperature)
            )
            mash_out_duration_seconds = _eff(
                ov.mash_out_duration_seconds, to_seconds(recognized.step_time)
            )
        else:
            mash_out_name = "Mash Out"
            mash_out_temperature_c = _eff(ov.mash_out_temperature_c, MASH_OUT_TEMPERATURE_C)
            mash_out_duration_seconds = _eff(
                ov.mash_out_duration_seconds, MASH_OUT_DURATION_SECONDS
            )

    if ov.mash_in_temperature_c is not None:
        mash_in_c = ov.mash_in_temperature_c
    elif rests:
        mash_in_c = to_celsius(rests[0].step_temperature) + MASH_IN_DELTA_C
    else:
        raise ValueError("mash-in temperature or at least one mash step is required")

    mash_in_alerts = []
    if _eff(ov.include_temperature_alerts, True):
        mash_in_alerts.append(
            _alert(
                _eff(ov.mash_in_alert_text, DEFAULT_MASH_IN_ALERT),
                "Temperature",
                temperature=mash_in_c,
            )
        )
    mash_in_alerts.extend(
        _alert(addition.text, "Temperature", temperature=addition.temperature_c)
        for addition in ov.mash_additions or []
    )
    steps = [
        _step(
            "Mash In",
            mash_in_c,
            end_type="Manual",
            duration_type="Manual",
            length=None,
            heating=ov.heat_power_pct,
            pid=False,
            alerts=mash_in_alerts,
        )
    ]

    previous_c = mash_in_c
    rest_end_alerts_by_index = {alert.rest_index: alert.text for alert in ov.rest_end_alerts or []}
    for index, rest in enumerate(rests):
        end_alerts = (
            [_alert(rest_end_alerts_by_index[index], "StepEnd")]
            if index in rest_end_alerts_by_index
            else []
        )
        previous_c = _rest_step(
            steps,
            name=rest.name or f"{to_celsius(rest.step_temperature):g} °C",
            temperature_c=to_celsius(rest.step_temperature),
            duration_seconds=to_seconds(rest.step_time),
            heating=ov.rest_power_pct,
            pid=_eff(ov.mash_pid_enabled, False),
            end_alerts=end_alerts,
            previous_temperature=previous_c,
            transition_heating=ov.heat_power_pct,
        )

    if mash_out_name is not None:
        end_alerts = (
            [_alert(ov.mash_out_end_alert_text, "StepEnd")] if ov.mash_out_end_alert_text else []
        )
        previous_c = _rest_step(
            steps,
            name=mash_out_name,
            temperature_c=mash_out_temperature_c,
            duration_seconds=mash_out_duration_seconds,
            heating=ov.rest_power_pct,
            pid=_eff(ov.mash_pid_enabled, False),
            end_alerts=end_alerts,
            previous_temperature=previous_c,
            transition_heating=ov.heat_power_pct,
        )

    if _eff(ov.include_sparge, True):
        sparge_c = _eff(ov.sparge_temperature_c, SPARGE_TEMPERATURE_C)
        if (
            mash_out_name is None
            and previous_c < sparge_c
            and ov.heat_power_pct is not None
            and ov.rest_power_pct is not None
            and ov.heat_power_pct != ov.rest_power_pct
        ):
            steps.append(
                _step(
                    f"→ {sparge_c:g} °C",
                    sparge_c,
                    end_type="Temperature",
                    duration_type="Temperature",
                    length=None,
                    heating=ov.heat_power_pct,
                    pid=False,
                )
            )
        steps.append(
            _step(
                "Sparge",
                sparge_c,
                end_type="Manual",
                duration_type="Manual",
                length=None,
                heating=0,
                pid=False,
                alerts=[_alert(ov.sparge_alert_text, "StepStart")] if ov.sparge_alert_text else [],
            )
        )

    boil = recipe.boil
    boil_steps = boil.boil_steps if boil and boil.boil_steps else []
    boil_seconds = to_seconds(boil.boil_time) if boil else None

    if ov.boil_temperature_c is not None:
        boil_c = ov.boil_temperature_c
    elif boil_steps and boil_steps[0].start_temperature is not None:
        boil_c = to_celsius(boil_steps[0].start_temperature)
    else:
        boil_c = BOIL_TEMPERATURE_C

    has_whirlpool = len(boil_steps) == 2
    boil_alerts: list[dict] = []
    whirlpool_additions: list[tuple] = []
    additions = [
        *recipe.ingredients.fermentable_additions,
        *(recipe.ingredients.hop_additions or []),
        *(recipe.ingredients.miscellaneous_additions or []),
    ]
    for addition in additions:
        timing = addition.timing
        if not timing or timing.use != "add_to_boil":
            continue
        time_s = to_seconds(timing.time) if timing.time is not None else None
        duration_s = to_seconds(timing.duration) if timing.duration is not None else None
        if boil_seconds is None:
            if time_s is not None or duration_s is not None:
                raise ValueError(
                    f"boil duration is required when timed boil additions are present: {addition.name}"
                )
            continue
        if time_s is not None and time_s >= boil_seconds and has_whirlpool:
            whirlpool_additions.append((addition, time_s))
            continue
        if time_s is not None:
            length = time_s
        elif duration_s is not None:
            length = boil_seconds - duration_s
        else:
            continue
        if not 0 <= length <= boil_seconds:
            raise ValueError(f"boil addition occurs outside the boil: {addition.name}")
        text = (
            f"{format_amount(addition.amount)} {addition.name}"
            if addition.amount
            else addition.name
        )
        boil_alerts.append(_alert(text, "Duration", length=length))

    steps.append(
        _step(
            "Boil",
            boil_c,
            end_type="Duration" if boil_seconds is not None else "Manual",
            duration_type="Temperature" if boil_seconds is not None else "Manual",
            length=boil_seconds,
            heating=ov.heat_power_pct,
            pid=False,
            alerts=boil_alerts,
        )
    )

    if has_whirlpool:
        whirlpool_step = boil_steps[1]
        whirlpool_c = (
            to_celsius(whirlpool_step.start_temperature)
            if whirlpool_step.start_temperature is not None
            else boil_c
        )
        whirlpool_seconds = to_seconds(whirlpool_step.step_time)
        whirlpool_alerts = []
        if (
            whirlpool_step.start_temperature is not None
            and ov.whirlpool_temperature_alert_text
            and _eff(ov.include_temperature_alerts, True)
        ):
            whirlpool_alerts.append(
                _alert(ov.whirlpool_temperature_alert_text, "Temperature", temperature=whirlpool_c)
            )
        if ov.whirlpool_end_alert_text:
            whirlpool_alerts.append(_alert(ov.whirlpool_end_alert_text, "StepEnd"))
        for addition, time_s in whirlpool_additions:
            length = max(0, min(time_s - boil_seconds, whirlpool_seconds))
            text = (
                f"{format_amount(addition.amount)} {addition.name}"
                if addition.amount
                else addition.name
            )
            whirlpool_alerts.append(_alert(text, "Duration", length=length))
        steps.append(
            _step(
                whirlpool_step.name or "Whirlpool",
                whirlpool_c,
                end_type="Duration",
                duration_type="Temperature",
                length=whirlpool_seconds,
                heating=0,
                pid=False,
                alerts=whirlpool_alerts,
            )
        )

    steps.append(
        _step(
            "Cooling",
            _eff(ov.cooling_temperature_c, COOLING_TEMPERATURE_C),
            end_type="Temperature",
            duration_type="Temperature",
            length=None,
            heating=0,
            pid=False,
        )
    )

    for order, step in enumerate(steps):
        step["order"] = order
    profile = ProfileIn.model_validate(
        {
            "name": recipe.name.strip(),
            "description": recipe.notes.strip(),
            "public": False,
            "profile_type_id": None,
            "profile_type_name": None,
            "steps": steps,
            "alerts": [],
        }
    )
    return profile.model_dump()
