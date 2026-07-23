"""AI recipe wizard: BrewZilla profile generation with structural and semantic validation."""

import json
import logging
import math
from collections.abc import Callable, Sequence

from pydantic import ValidationError

from core.config import LLM_TEMPERATURE
from features.profiles.enums import (
    ALERT_TRIGGERS,
    CONTROL_TYPE_LABELS,
    CONTROL_TYPES,
    DURATION_TYPES,
    END_TYPE_LABELS,
    END_TYPES,
    STEP_NAME_MAX_LEN,
    STEP_NAME_MIN_LEN,
    STEP_REQUIRED_FIELDS,
    VALUE_OPERATORS,
)
from features.profiles.router import ProfileIn

from .services import _load_prompt, _run_chat_completion

logger = logging.getLogger(__name__)

RECIPE_WIZARD_SYSTEM_PROMPT = _load_prompt("recipe_wizard.md")
RECIPE_WIZARD_VALIDATOR_PROMPT = _load_prompt("recipe_wizard_validator.md")

_BREWZILLA_CONTROL_TYPES = ("Target", "Ramp")
_BREWZILLA_END_TYPES = ("Duration", "Temperature", "Manual")
_BREWZILLA_STEP_ALERT_TRIGGERS = ("StepStart", "StepEnd", "Duration", "Temperature")
_BREWZILLA_DURATION_TYPES = ("Start", "Temperature", "Manual")
_REQUIRED_BREWZILLA_STEPS = {
    "Mash In": ("mashin",),
    "Mash Out": ("mashout",),
    "Sparge": ("sparge",),
    "Boil": ("boil",),
    "Cooling": ("cooling",),
}
_ALERT_SCHEMA = {
    "type": "object",
    "required": [
        "id",
        "alertText",
        "trigger",
        "operator",
        "temperature",
        "gravity",
        "length",
    ],
    "properties": {
        "id": {"type": "null"},
        "alertText": {"type": "string", "minLength": 1},
        "trigger": {"type": "string", "enum": list(_BREWZILLA_STEP_ALERT_TRIGGERS)},
        "operator": {"type": ["string", "null"], "enum": [None, *VALUE_OPERATORS]},
        "temperature": {
            "type": ["number", "null"],
            "description": (
                "Required numeric temperature when trigger is Temperature; otherwise null. "
                "For the Mash In alert it must equal the Mash In step temperature."
            ),
        },
        "gravity": {"type": "null"},
        "length": {"type": ["integer", "null"], "minimum": 0},
    },
    "additionalProperties": False,
}
_STEP_SCHEMA = {
    "type": "object",
    "required": [
        "id",
        "name",
        "order",
        "controlType",
        "endType",
        "durationType",
        "operator",
        "length",
        "temperature",
        "minTemperature",
        "maxTemperature",
        "gravity",
        "pumpEnabled",
        "pumpUtilisation",
        "heatingUtilisation",
        "pidEnabled",
        "sensorDifferential",
        "alerts",
    ],
    "properties": {
        "id": {"type": "null"},
        "name": {
            "type": "string",
            "minLength": STEP_NAME_MIN_LEN,
            "maxLength": STEP_NAME_MAX_LEN,
        },
        "order": {"type": "integer", "minimum": 0},
        "controlType": {"type": "string", "enum": list(_BREWZILLA_CONTROL_TYPES)},
        "endType": {"type": "string", "enum": list(_BREWZILLA_END_TYPES)},
        "durationType": {"type": "string", "enum": list(_BREWZILLA_DURATION_TYPES)},
        "operator": {"type": ["string", "null"], "enum": [None, *VALUE_OPERATORS]},
        "length": {"type": ["integer", "null"], "minimum": 1},
        "temperature": {"type": ["number", "null"]},
        "minTemperature": {"type": "null"},
        "maxTemperature": {"type": "null"},
        "gravity": {"type": "null"},
        "pumpEnabled": {"type": ["boolean", "null"]},
        "pumpUtilisation": {
            "type": ["number", "null"],
            "minimum": 0,
            "maximum": 100,
            "description": "Pump output percentage for this entire step.",
        },
        "heatingUtilisation": {
            "type": ["number", "null"],
            "minimum": 0,
            "maximum": 100,
            "description": (
                "Heater output percentage for this entire step. Use heating power for Mash In, "
                "heat-up transitions and Boil; use holding power only for timed mash rests."
            ),
        },
        "pidEnabled": {
            "type": ["boolean", "null"],
            "description": "Enable PID for mash rests only when requested; do not inherit it on Boil.",
        },
        "sensorDifferential": {"type": ["number", "null"]},
        "alerts": {"type": "array", "items": _ALERT_SCHEMA},
    },
    "additionalProperties": False,
}
_RECIPE_WIZARD_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "recipe_wizard_profile",
        "strict": True,
        "schema": {
            "type": "object",
            "required": [
                "name",
                "description",
                "public",
                "profile_type_id",
                "profile_type_name",
                "steps",
                "alerts",
            ],
            "properties": {
                "name": {
                    "type": "string",
                    "minLength": STEP_NAME_MIN_LEN,
                    "maxLength": STEP_NAME_MAX_LEN,
                },
                "description": {"type": "string", "minLength": 12},
                "public": {"type": "boolean", "enum": [False]},
                "profile_type_id": {"type": "null"},
                "profile_type_name": {"type": "null"},
                "steps": {
                    "type": "array",
                    "minItems": 1,
                    "items": _STEP_SCHEMA,
                },
                "alerts": {"type": "array", "maxItems": 0, "items": _ALERT_SCHEMA},
            },
            "additionalProperties": False,
        },
    },
}
_RECIPE_WIZARD_VALIDATOR_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "recipe_wizard_validation",
        "strict": True,
        "schema": {
            "type": "object",
            "required": ["valid", "errors"],
            "properties": {
                "valid": {"type": "boolean"},
                "errors": {
                    "type": "array",
                    "maxItems": 20,
                    "items": {"type": "string", "minLength": 1, "maxLength": 500},
                },
            },
            "additionalProperties": False,
        },
    },
}


def _enum_contract_block() -> str:
    return "\n".join(
        [
            "[PROFILE CONTRACT]",
            f"CONTROL_TYPES={', '.join(CONTROL_TYPES)}",
            f"END_TYPES={', '.join(END_TYPES)}",
            f"DURATION_TYPES={', '.join(DURATION_TYPES)}",
            f"ALERT_TRIGGERS={', '.join(ALERT_TRIGGERS)}",
            f"VALUE_OPERATORS={', '.join(VALUE_OPERATORS)}",
            f"CONTROL_TYPE_LABELS={json.dumps(CONTROL_TYPE_LABELS, ensure_ascii=False)}",
            f"END_TYPE_LABELS={json.dumps(END_TYPE_LABELS, ensure_ascii=False)}",
            f"STEP_NAME_MIN_LEN={STEP_NAME_MIN_LEN}",
            f"STEP_NAME_MAX_LEN={STEP_NAME_MAX_LEN}",
            f"STEP_REQUIRED_FIELDS={', '.join(STEP_REQUIRED_FIELDS)}",
            f"BREWZILLA_ALLOWED_CONTROL_TYPES={', '.join(_BREWZILLA_CONTROL_TYPES)}",
            f"BREWZILLA_ALLOWED_END_TYPES={', '.join(_BREWZILLA_END_TYPES)}",
            f"BREWZILLA_ALLOWED_STEP_ALERT_TRIGGERS={', '.join(_BREWZILLA_STEP_ALERT_TRIGGERS)}",
            "BREWZILLA_FORBIDDEN=FreeRise, Gravity, GravityVelocity, gravity fields, gravity alerts",
        ]
    )


def _recipe_wizard_messages(description: str, history: Sequence[dict[str, str]] = ()) -> list[dict]:
    return [
        {
            "role": "system",
            "content": f"{RECIPE_WIZARD_SYSTEM_PROMPT.strip()}\n\n{_enum_contract_block()}",
        },
        *history,
        {"role": "user", "content": description.strip()},
    ]


def _as_finite_number(value, field_name: str) -> float:
    if not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"{field_name} must be a finite number")
    return float(value)


def _normalize_name_token(value: str | None) -> str:
    return "".join(character for character in (value or "").lower() if character.isalnum())


def _matches_step_aliases(step_name: str | None, aliases: tuple[str, ...]) -> bool:
    normalized = _normalize_name_token(step_name)
    return normalized in aliases


def _repair_hint_from_error(error: Exception) -> str:
    text = str(error)
    if "profile description summary is required" in text:
        return "Fill description with a concise recipe summary in the user's language."
    if "missing required BrewZilla steps:" in text:
        return (
            "Add the required BrewZilla skeleton: Mash In, clearly named mash rests, "
            "Mash Out, Sparge, Boil, and Cooling."
        )
    if "mash-in temperature alert is required" in text:
        return (
            "Add a trigger='Temperature' alert at the Mash In target, with a clear "
            "instruction to add grain in the user's language."
        )
    if "alert" in text and "temperature must be a finite number" in text:
        return (
            "Set a numeric temperature for every trigger='Temperature' alert. "
            "For Mash In it must equal the step temperature."
        )
    if "mash-in alert temperature must match step temperature" in text:
        return "Copy the exact Mash In step temperature into its Temperature alert."
    if "mash-in temperature must be 2-4 degrees above first rest" in text:
        return (
            f"{text}. Set Mash In 2–4 °C above the first rest and use the same "
            "value in its Temperature alert."
        )
    if "mash-in must wait for manual completion" in text:
        return (
            "Mash In must hold its target until grain addition is manually completed: "
            "controlType='Target', endType='Manual', durationType='Manual', length=null."
        )
    if "heating utilisation does not match profile heat power" in text:
        return (
            f"{text}. Fix this step: heatingUtilisation must equal the maximum heating "
            "power already present in the profile. Use it for Mash In, heat transitions, "
            "and Boil; lower power is only for rests."
        )
    if "heating utilisation appears to use a fractional percentage" in text:
        return "Write heating percentages on the 0–100 scale: 90%=90 and 50%=50, never 0.9 or 0.5."
    if "rest must have a separate heating step" in text:
        return (
            "When heating and hold power differ, add a separate full-power Target + "
            "Temperature heat-up step before each rest, followed by a Target + Duration "
            "hold step at rest power with PID."
        )
    if "boil must not use rest PID" in text:
        return "Do not enable rest PID for Boil; keep boil power fixed."
    if "boil completion configuration is invalid" in text:
        return (
            "For a timed Boil use Target + Duration, durationType='Temperature', and its "
            "duration in length. For an untimed Boil use Target + Manual, "
            "durationType='Manual', and length=null."
        )
    if "mash-out completion configuration is invalid" in text:
        return (
            "Mash Out must be Target + Duration with durationType='Temperature' and a "
            "positive length."
        )
    if "mash-out heating utilisation does not match rest power" in text:
        return "Use the same hold power for Mash Out as for the other mash rests."
    if "mash-out must use rest PID" in text:
        return "Enable PID for Mash Out when the other mash rests use PID."
    if "sparge completion configuration is invalid" in text:
        return "Sparge must be Target + Manual with durationType='Manual' and length=null."
    if "cooling configuration is invalid" in text:
        return (
            "Cooling must be Target + Temperature with durationType='Temperature', "
            "length=null, heatingUtilisation=0 or null, and PID disabled."
        )
    if "target step durationType must not be Start" in text:
        return "Use durationType='Start' only for Ramp steps, never for Target steps."
    if "redundant heat transition" in text:
        return "Remove the heat transition because the preceding step already has that target."
    if "alert" in text and "text is required" in text:
        return "Every step alert requires a clear non-empty alertText in the user's language."
    if "length must be a positive integer" in text:
        return (
            "For controlType='Ramp' or endType='Duration', set a positive integer length "
            "in seconds. Use Target + Manual for untimed Mash In and Sparge, and Target + "
            "Temperature for Cooling."
        )
    if "trigger is invalid" in text:
        return (
            "A BrewZilla step-alert trigger must be StepStart, StepEnd, Duration, or Temperature."
        )
    if "controlType is invalid" in text:
        return "Use only controlType='Target' or 'Ramp' for BrewZilla."
    if "endType is invalid" in text:
        return "Use only endType='Duration', 'Temperature', or 'Manual' for BrewZilla."
    if "durationType is invalid" in text:
        return "Use a valid non-empty durationType from the allowed set."
    if "target duration timer must start at temperature" in text:
        return (
            "For a Target step with endType='Duration', set durationType='Temperature' "
            "so the hold starts only after reaching the target."
        )
    if "mash-out temperature must be 78" in text:
        return "Set the Mash Out target temperature to 78 °C."
    if "alert occurs after step end" in text:
        return "A Duration alert must not fire after the step ends."
    if "Recipe mismatches:" in text:
        return text
    if "fixed profile fields are invalid" in text:
        return "Set public=false, profile_type_id=null, profile_type_name=null, and root alerts=[]."
    if "profile name length is invalid" in text:
        return "Set name to 4–50 characters in the user's language."
    if "profile root must be an object" in text:
        return "Return one top-level JSON object, not an array or markdown."
    return f"Fix the response according to this validation error: {text}"


def _validate_generated_profile(raw: str) -> dict:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise TypeError("profile root must be an object")
    if (
        data.get("public") is not False
        or data.get("profile_type_id") is not None
        or data.get("profile_type_name") is not None
        or data.get("alerts") != []
    ):
        raise ValueError("fixed profile fields are invalid")

    profile = ProfileIn.model_validate(data)
    name = profile.name.strip()
    description_summary = profile.description.strip() if profile.description else ""
    if not STEP_NAME_MIN_LEN <= len(name) <= STEP_NAME_MAX_LEN:
        raise ValueError("profile name length is invalid")
    if len(description_summary) < 12:
        raise ValueError("profile description summary is required")
    if not profile.steps:
        raise ValueError("profile must contain at least one step")

    found_required_steps = {name: False for name in _REQUIRED_BREWZILLA_STEPS}
    mash_in_temperature_alerts = 0
    heating_values = [
        _as_finite_number(step.heatingUtilisation, "heating utilisation")
        for step in profile.steps
        if step.heatingUtilisation is not None
    ]
    profile_heat_power = max(heating_values, default=None)
    positive_heating_values = [value for value in heating_values if value > 0]
    if positive_heating_values and max(positive_heating_values) <= 1:
        raise ValueError("heating utilisation appears to use a fractional percentage")
    mash_rests = [
        step
        for step in profile.steps
        if step.controlType == "Target"
        and step.endType == "Duration"
        and not _matches_step_aliases(step.name, _REQUIRED_BREWZILLA_STEPS["Mash Out"])
        and not _matches_step_aliases(step.name, _REQUIRED_BREWZILLA_STEPS["Boil"])
    ]
    lower_rest_powers = {
        float(step.heatingUtilisation)
        for step in mash_rests
        if profile_heat_power is not None
        and step.heatingUtilisation is not None
        and step.heatingUtilisation < profile_heat_power
    }
    profile_rest_power = next(iter(lower_rest_powers)) if len(lower_rest_powers) == 1 else None
    mash_rests_use_pid = any(step.pidEnabled is True for step in mash_rests)

    for order, step in enumerate(profile.steps):
        step_name = (step.name or "").strip()
        if not STEP_NAME_MIN_LEN <= len(step_name) <= STEP_NAME_MAX_LEN:
            raise ValueError(f"step {order} name length is invalid")
        for required_name, aliases in _REQUIRED_BREWZILLA_STEPS.items():
            if _matches_step_aliases(step_name, aliases):
                found_required_steps[required_name] = True
        if step.controlType not in _BREWZILLA_CONTROL_TYPES:
            raise ValueError(f"step {order} controlType is invalid")
        if step.endType not in _BREWZILLA_END_TYPES:
            raise ValueError(f"step {order} endType is invalid")
        if step.durationType not in _BREWZILLA_DURATION_TYPES:
            raise ValueError(f"step {order} durationType is invalid")
        if step.operator not in (None, *VALUE_OPERATORS):
            raise ValueError(f"step {order} operator is invalid")
        if step.id is not None or any(
            value is not None for value in (step.minTemperature, step.maxTemperature, step.gravity)
        ):
            raise ValueError(f"step {order} contains forbidden generated fields")
        if step.controlType in _BREWZILLA_CONTROL_TYPES:
            _as_finite_number(step.temperature, f"step {order} temperature")
        for field_name, value in (
            ("pump utilisation", step.pumpUtilisation),
            ("heating utilisation", step.heatingUtilisation),
        ):
            if value is not None and not 0 <= _as_finite_number(value, field_name) <= 100:
                raise ValueError(f"step {order} {field_name} must be between 0 and 100")
        if step.controlType == "Ramp" or step.endType == "Duration":
            if not isinstance(step.length, int) or step.length <= 0:
                raise ValueError(f"step {order} length must be a positive integer")
        is_mash_in = _matches_step_aliases(step_name, _REQUIRED_BREWZILLA_STEPS["Mash In"])
        is_mash_out = _matches_step_aliases(step_name, _REQUIRED_BREWZILLA_STEPS["Mash Out"])
        is_sparge = _matches_step_aliases(step_name, _REQUIRED_BREWZILLA_STEPS["Sparge"])
        is_boil = _matches_step_aliases(step_name, _REQUIRED_BREWZILLA_STEPS["Boil"])
        is_cooling = _matches_step_aliases(step_name, _REQUIRED_BREWZILLA_STEPS["Cooling"])
        if is_mash_in and (
            step.controlType != "Target"
            or step.endType != "Manual"
            or step.durationType != "Manual"
            or step.length is not None
        ):
            raise ValueError(f"step {order} mash-in must wait for manual completion")
        if (
            step.controlType == "Target"
            and step.endType != "Duration"
            and step.durationType == "Start"
        ):
            raise ValueError(f"step {order} target step durationType must not be Start")
        if (
            step.controlType == "Target"
            and step.endType == "Duration"
            and step.durationType != "Temperature"
        ):
            raise ValueError(f"step {order} target duration timer must start at temperature")
        if is_mash_out and step.temperature != 78:
            raise ValueError(f"step {order} mash-out temperature must be 78")
        if is_mash_out and (
            step.controlType != "Target"
            or step.endType != "Duration"
            or step.durationType != "Temperature"
        ):
            raise ValueError(f"step {order} mash-out completion configuration is invalid")
        if (
            is_mash_out
            and profile_rest_power is not None
            and step.heatingUtilisation != profile_rest_power
        ):
            raise ValueError(f"step {order} mash-out heating utilisation does not match rest power")
        if is_mash_out and mash_rests_use_pid and step.pidEnabled is not True:
            raise ValueError(f"step {order} mash-out must use rest PID")
        if is_sparge and (
            step.controlType != "Target"
            or step.endType != "Manual"
            or step.durationType != "Manual"
            or step.length is not None
        ):
            raise ValueError(f"step {order} sparge completion configuration is invalid")
        timed_boil = (
            step.controlType == "Target"
            and step.endType == "Duration"
            and step.durationType == "Temperature"
            and isinstance(step.length, int)
            and step.length > 0
        )
        manual_boil = (
            step.controlType == "Target"
            and step.endType == "Manual"
            and step.durationType == "Manual"
            and step.length is None
        )
        if is_boil and not (timed_boil or manual_boil):
            raise ValueError(f"step {order} boil completion configuration is invalid")
        if is_cooling and (
            step.controlType != "Target"
            or step.endType != "Temperature"
            or step.durationType != "Temperature"
            or step.length is not None
            or step.heatingUtilisation not in (None, 0)
            or step.pidEnabled is True
        ):
            raise ValueError(f"step {order} cooling configuration is invalid")
        is_heat_transition = (
            step.controlType == "Target" and step.endType == "Temperature" and not is_cooling
        )
        previous = profile.steps[order - 1] if order > 0 else None
        if is_heat_transition and previous is not None and previous.temperature == step.temperature:
            raise ValueError(f"step {order} redundant heat transition")
        if profile_heat_power is not None and (is_mash_in or is_boil or is_heat_transition):
            if step.heatingUtilisation != profile_heat_power:
                raise ValueError(
                    f"step {order} heating utilisation does not match profile heat power: "
                    f"actual={step.heatingUtilisation!r}, expected={profile_heat_power:g}"
                )
        if is_boil and step.pidEnabled is True:
            raise ValueError(f"step {order} boil must not use rest PID")
        if (
            profile_heat_power is not None
            and step.heatingUtilisation is not None
            and step.heatingUtilisation < profile_heat_power
            and step.controlType == "Target"
            and step.endType == "Duration"
            and not is_boil
        ):
            previous_is_mash_in = previous is not None and _matches_step_aliases(
                previous.name, _REQUIRED_BREWZILLA_STEPS["Mash In"]
            )
            if (
                previous is None
                or previous.controlType != "Target"
                or (
                    previous.endType != "Temperature"
                    and not (previous_is_mash_in and previous.endType == "Manual")
                )
                or previous.temperature != step.temperature
                or previous.heatingUtilisation != profile_heat_power
            ):
                raise ValueError(f"step {order} rest must have a separate heating step")
        for alert_index, alert in enumerate(step.alerts):
            if alert.trigger not in _BREWZILLA_STEP_ALERT_TRIGGERS:
                raise ValueError(f"step {order} alert {alert_index} trigger is invalid")
            if alert.operator not in (None, *VALUE_OPERATORS):
                raise ValueError(f"step {order} alert {alert_index} operator is invalid")
            if not (alert.alertText or "").strip():
                raise ValueError(f"step {order} alert {alert_index} text is required")
            if alert.id is not None or alert.gravity is not None:
                raise ValueError(
                    f"step {order} alert {alert_index} contains forbidden generated fields"
                )
            if alert.trigger == "Duration":
                if not isinstance(alert.length, int) or alert.length < 0:
                    raise ValueError(
                        f"step {order} alert {alert_index} length must be a non-negative integer"
                    )
                if step.length is not None and alert.length > step.length:
                    raise ValueError(f"step {order} alert {alert_index} occurs after step end")
            if alert.trigger == "Temperature":
                _as_finite_number(
                    alert.temperature, f"step {order} alert {alert_index} temperature"
                )
                if _matches_step_aliases(step_name, _REQUIRED_BREWZILLA_STEPS["Mash In"]):
                    if alert.temperature != step.temperature:
                        raise ValueError(
                            f"step {order} mash-in alert temperature must match step temperature"
                        )
                    mash_in_temperature_alerts += 1

    missing_steps = [name for name, found in found_required_steps.items() if not found]
    if missing_steps:
        raise ValueError(f"missing required BrewZilla steps: {', '.join(missing_steps)}")
    if mash_in_temperature_alerts == 0:
        raise ValueError("mash-in temperature alert is required")
    mash_in_index, mash_in = next(
        (index, step)
        for index, step in enumerate(profile.steps)
        if _matches_step_aliases(step.name, _REQUIRED_BREWZILLA_STEPS["Mash In"])
    )
    first_rest = next(
        (
            step
            for step in profile.steps[mash_in_index + 1 :]
            if step.controlType == "Target"
            and step.endType == "Duration"
            and not _matches_step_aliases(step.name, _REQUIRED_BREWZILLA_STEPS["Mash Out"])
            and not _matches_step_aliases(step.name, _REQUIRED_BREWZILLA_STEPS["Boil"])
        ),
        None,
    )
    if first_rest is not None:
        delta = float(mash_in.temperature) - float(first_rest.temperature)
        if not 2 <= delta <= 4:
            expected_min = float(first_rest.temperature) + 2
            expected_max = float(first_rest.temperature) + 4
            raise ValueError(
                "mash-in temperature must be 2-4 degrees above first rest: "
                f"actual={mash_in.temperature:g}, first_rest={first_rest.temperature:g}, "
                f"expected={expected_min:g}-{expected_max:g}"
            )

    normalized = profile.model_dump()
    normalized["name"] = name
    normalized["description"] = description_summary
    normalized["public"] = False
    normalized["profile_type_id"] = None
    normalized["profile_type_name"] = None
    normalized["alerts"] = []
    normalized["steps"] = [
        {
            **step,
            "name": (step.get("name") or "").strip(),
            "order": order,
            "alerts": [
                {**alert, "alertText": (alert.get("alertText") or "").strip()}
                for alert in step.get("alerts", [])
            ],
        }
        for order, step in enumerate(normalized["steps"])
    ]
    return normalized


async def _semantic_profile_errors(description: str, profile: dict) -> list[str]:
    raw = await _run_chat_completion(
        [
            {"role": "system", "content": RECIPE_WIZARD_VALIDATOR_PROMPT},
            {
                "role": "user",
                "content": (
                    f"<source_description>{description}</source_description>\n"
                    f"<candidate_profile>{json.dumps(profile, ensure_ascii=False, separators=(',', ':'))}"
                    "</candidate_profile>"
                ),
            },
        ],
        tools=None,
        current_session_id=None,
        temperature=0,
        response_format=_RECIPE_WIZARD_VALIDATOR_RESPONSE_FORMAT,
    )
    result = json.loads(raw)
    valid = result.get("valid")
    errors = result.get("errors")
    if (
        not isinstance(valid, bool)
        or not isinstance(errors, list)
        or any(not isinstance(error, str) or not error.strip() for error in errors)
        or valid == bool(errors)
    ):
        raise ValueError("semantic validator returned an invalid result")
    return [error.strip() for error in errors]


def _semantic_validation_candidate(raw: str) -> dict | None:
    data = json.loads(raw)
    if not isinstance(data, dict):
        return None
    profile = ProfileIn.model_validate(data)
    if not profile.description or not profile.description.strip() or not profile.steps:
        return None
    return profile.model_dump()


async def _validated_generated_profile(
    raw: str,
    description: str,
    on_progress: Callable[[str], None] | None,
    *,
    retry: bool,
) -> dict:
    on_progress and on_progress("checking_fixed_structure" if retry else "checking_structure")
    structural_error: Exception | None = None
    try:
        profile = _validate_generated_profile(raw)
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as error:
        structural_error = error
        candidate = _semantic_validation_candidate(raw)
        if candidate is None:
            raise
    else:
        candidate = profile

    on_progress and on_progress("checking_fixed_recipe" if retry else "checking_recipe")
    semantic_errors = await _semantic_profile_errors(description, candidate)
    if structural_error or semantic_errors:
        error_groups = []
        if structural_error:
            error_groups.append(f"Structural errors:\n- {structural_error}")
        if semantic_errors:
            error_groups.append("Recipe mismatches:\n- " + "\n- ".join(semantic_errors))
        raise ValueError("\n".join(error_groups))
    return profile


async def generate_profile(
    description: str,
    on_progress: Callable[[str], None] | None = None,
) -> dict:
    messages = _recipe_wizard_messages(description)
    on_progress and on_progress("generating")
    raw = await _run_chat_completion(
        messages,
        tools=None,
        current_session_id=None,
        temperature=LLM_TEMPERATURE,
        response_format=_RECIPE_WIZARD_RESPONSE_FORMAT,
    )
    try:
        return await _validated_generated_profile(raw, description, on_progress, retry=False)
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as error:
        on_progress and on_progress("repairing")
        repair_hint = _repair_hint_from_error(error)
        retry_messages = [
            *messages,
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": (
                    "Fix the response and return the complete JSON object. "
                    "Preserve the language detected from the original user recipe for name, "
                    "description, non-service step names, and alertText; required service step names "
                    "remain English. Use hidden RAPT setup defaults unless overridden: "
                    "temperature alerts = yes, sparge = yes, mash-out = yes, whirlpool = no. "
                    "description is required and must be a concise recipe summary. "
                    "Required skeleton: Mash In, clearly named mash rests, Mash Out, Sparge, "
                    "Boil, Cooling. For Target + Duration always use "
                    "durationType='Temperature'. Defaults: Mash Out 78 °C, Sparge 78 °C, "
                    "Cooling 20 °C. Add Duration alerts to Boil for all timed additions, "
                    "including hops and spices. "
                    f"Repair: {repair_hint} "
                    f"Validation error: {error}"
                ),
            },
        ]
        retry_raw = await _run_chat_completion(
            retry_messages,
            tools=None,
            current_session_id=None,
            temperature=LLM_TEMPERATURE,
            response_format=_RECIPE_WIZARD_RESPONSE_FORMAT,
        )
        try:
            return await _validated_generated_profile(
                retry_raw, description, on_progress, retry=True
            )
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as retry_error:
            logger.warning("Recipe wizard returned invalid profile twice: %s", retry_error)
            raise ValueError("Модель не смогла собрать корректный профиль") from retry_error
