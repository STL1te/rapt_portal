"""AI recipe wizard: semantic extraction followed by deterministic profile assembly."""

import json
import logging
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.config import LLM_MODEL, LLM_TEMPERATURE, LLM_TOP_P
from features.profiles.enums import STEP_NAME_MAX_LEN, STEP_NAME_MIN_LEN
from features.profiles.router import ProfileIn

from . import services as ai_services
from .services import _load_prompt, _run_chat_completion

logger = logging.getLogger(__name__)

RECIPE_WIZARD_SYSTEM_PROMPT = _load_prompt("recipe_wizard.md")
RECIPE_WIZARD_VALIDATOR_PROMPT = _load_prompt("recipe_wizard_validator.md")


class _SpecModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RestSpec(_SpecModel):
    name: str = Field(min_length=STEP_NAME_MIN_LEN, max_length=STEP_NAME_MAX_LEN)
    temperature_c: float = Field(allow_inf_nan=False)
    duration_seconds: int = Field(gt=0)
    temperature_alert_text: str | None = Field(default=None, min_length=1)
    end_alert_text: str | None = Field(default=None, min_length=1)


class BoilAdditionSpec(_SpecModel):
    text: str = Field(min_length=1, max_length=500)
    timing_reference: Literal["from_start", "before_end"]
    offset_seconds: int = Field(ge=0)


class RecipeSpec(_SpecModel):
    name: str = Field(min_length=STEP_NAME_MIN_LEN, max_length=STEP_NAME_MAX_LEN)
    description: str = Field(min_length=12, max_length=2000)
    mash_in_temperature_c: float | None = Field(default=None, allow_inf_nan=False)
    mash_in_alert_text: str | None = Field(default=None, min_length=1, max_length=500)
    mash_rests: list[RestSpec] = Field(default_factory=list)
    include_temperature_alerts: bool = True
    include_sparge: bool = True
    include_mash_out: bool = True
    heat_power_pct: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    rest_power_pct: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    mash_pid_enabled: bool = False
    mash_out_duration_seconds: int = Field(default=600, gt=0)
    mash_out_end_alert_text: str | None = Field(default=None, min_length=1, max_length=500)
    sparge_alert_text: str | None = Field(default=None, min_length=1, max_length=500)
    boil_temperature_c: float = Field(default=100, allow_inf_nan=False)
    boil_duration_seconds: int | None = Field(default=None, gt=0)
    boil_additions: list[BoilAdditionSpec] = Field(default_factory=list)
    whirlpool: RestSpec | None = None
    cooling_temperature_c: float = Field(default=20, allow_inf_nan=False)


_RECIPE_SPEC_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_recipe_spec",
        "description": (
            "Submit the recipe facts and user-facing text. The server applies all BrewZilla "
            "step, alert, ordering, power, PID, and default rules."
        ),
        "parameters": RecipeSpec.model_json_schema(),
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


def _recipe_wizard_messages(description: str, correction: str | None = None) -> list[dict]:
    messages = [
        {"role": "system", "content": RECIPE_WIZARD_SYSTEM_PROMPT.strip()},
        {"role": "user", "content": description.strip()},
    ]
    if correction:
        messages.append({"role": "user", "content": correction})
    return messages


async def _extract_recipe_spec(messages: list[dict]) -> RecipeSpec:
    request = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": LLM_TEMPERATURE,
        "top_p": LLM_TOP_P,
        "tools": [_RECIPE_SPEC_TOOL],
        "tool_choice": "required",
    }
    async with ai_services._new_llm_client() as client:
        response = await client.chat.completions.create(**request)

    tool_calls = getattr(response.choices[0].message, "tool_calls", None) or []
    if len(tool_calls) != 1 or tool_calls[0].function.name != "submit_recipe_spec":
        raise ValueError("model must call submit_recipe_spec exactly once")
    try:
        arguments = json.loads(tool_calls[0].function.arguments)
    except json.JSONDecodeError as error:
        raise ValueError("submit_recipe_spec arguments must be valid JSON") from error
    return RecipeSpec.model_validate(arguments)


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


def _temperature_alerts(rest: RestSpec) -> list[dict]:
    if not rest.temperature_alert_text:
        return []
    return [
        _alert(
            rest.temperature_alert_text,
            "Temperature",
            temperature=rest.temperature_c,
        )
    ]


def _end_alerts(rest: RestSpec) -> list[dict]:
    return [_alert(rest.end_alert_text, "StepEnd")] if rest.end_alert_text else []


def _append_rest(
    steps: list[dict],
    rest: RestSpec,
    spec: RecipeSpec,
    previous_temperature: float,
) -> float:
    temperature_alerts = _temperature_alerts(rest) if spec.include_temperature_alerts else []
    separate_transition = (
        spec.heat_power_pct is not None
        and spec.rest_power_pct is not None
        and spec.heat_power_pct != spec.rest_power_pct
        and previous_temperature < rest.temperature_c
    )
    if separate_transition:
        steps.append(
            _step(
                f"→ {rest.temperature_c:g} °C",
                rest.temperature_c,
                end_type="Temperature",
                duration_type="Temperature",
                length=None,
                heating=spec.heat_power_pct,
                pid=False,
                alerts=temperature_alerts,
            )
        )
        temperature_alerts = []
    steps.append(
        _step(
            rest.name,
            rest.temperature_c,
            end_type="Duration",
            duration_type="Temperature",
            length=rest.duration_seconds,
            heating=spec.rest_power_pct,
            pid=spec.mash_pid_enabled,
            alerts=[*temperature_alerts, *_end_alerts(rest)],
        )
    )
    return rest.temperature_c


def _boil_alerts(spec: RecipeSpec) -> list[dict]:
    if spec.boil_additions and spec.boil_duration_seconds is None:
        raise ValueError("boil duration is required when timed boil additions are present")

    alerts = []
    for addition in spec.boil_additions:
        duration = spec.boil_duration_seconds
        if duration is None:
            raise ValueError("boil duration is required when timed boil additions are present")
        length = (
            addition.offset_seconds
            if addition.timing_reference == "from_start"
            else duration - addition.offset_seconds
        )
        if not 0 <= length <= duration:
            raise ValueError(f"boil addition occurs outside the boil: {addition.text}")
        alerts.append(_alert(addition.text, "Duration", length=length))
    return alerts


def compile_recipe(spec: RecipeSpec) -> dict:
    """Compile semantic recipe facts into the only low-level profile shape we emit."""
    mash_rests = list(spec.mash_rests)
    mash_out = None
    if spec.include_mash_out:
        mash_out = RestSpec(
            name="Mash Out",
            temperature_c=78,
            duration_seconds=spec.mash_out_duration_seconds,
            end_alert_text=spec.mash_out_end_alert_text,
        )
        if mash_rests and mash_rests[-1].temperature_c == 78:
            mash_out = mash_rests.pop().model_copy(update={"name": "Mash Out"})

    first_rest_temperature = mash_rests[0].temperature_c if mash_rests else None
    mash_in_temperature = spec.mash_in_temperature_c
    if mash_in_temperature is None:
        if first_rest_temperature is None:
            raise ValueError("mash-in temperature or at least one mash rest is required")
        mash_in_temperature = first_rest_temperature + 3

    if spec.include_temperature_alerts and not spec.mash_in_alert_text:
        raise ValueError("mash-in alert text is required when temperature alerts are enabled")
    mash_in_alerts = (
        [
            _alert(
                spec.mash_in_alert_text,
                "Temperature",
                temperature=mash_in_temperature,
            )
        ]
        if spec.include_temperature_alerts and spec.mash_in_alert_text
        else []
    )
    steps = [
        _step(
            "Mash In",
            mash_in_temperature,
            end_type="Manual",
            duration_type="Manual",
            length=None,
            heating=spec.heat_power_pct,
            pid=False,
            alerts=mash_in_alerts,
        )
    ]
    previous_temperature = mash_in_temperature
    for rest in mash_rests:
        previous_temperature = _append_rest(steps, rest, spec, previous_temperature)

    if mash_out:
        _append_rest(steps, mash_out, spec, previous_temperature)
    if spec.include_sparge:
        if (
            not mash_out
            and previous_temperature < 78
            and spec.heat_power_pct is not None
            and spec.rest_power_pct is not None
            and spec.heat_power_pct != spec.rest_power_pct
        ):
            steps.append(
                _step(
                    "→ 78 °C",
                    78,
                    end_type="Temperature",
                    duration_type="Temperature",
                    length=None,
                    heating=spec.heat_power_pct,
                    pid=False,
                )
            )
        steps.append(
            _step(
                "Sparge",
                78,
                end_type="Manual",
                duration_type="Manual",
                length=None,
                heating=0,
                pid=False,
                alerts=(
                    [_alert(spec.sparge_alert_text, "StepStart")] if spec.sparge_alert_text else []
                ),
            )
        )
    steps.append(
        _step(
            "Boil",
            spec.boil_temperature_c,
            end_type="Duration" if spec.boil_duration_seconds is not None else "Manual",
            duration_type="Temperature" if spec.boil_duration_seconds is not None else "Manual",
            length=spec.boil_duration_seconds,
            heating=spec.heat_power_pct,
            pid=False,
            alerts=_boil_alerts(spec),
        )
    )
    if spec.whirlpool:
        _append_rest(steps, spec.whirlpool, spec, spec.boil_temperature_c)
    steps.append(
        _step(
            "Cooling",
            spec.cooling_temperature_c,
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
            "name": spec.name.strip(),
            "description": spec.description.strip(),
            "public": False,
            "profile_type_id": None,
            "profile_type_name": None,
            "steps": steps,
            "alerts": [],
        }
    )
    return profile.model_dump()


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
    if not isinstance(result, dict):
        raise ValueError("semantic validator returned an invalid result")
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


async def _generate_once(
    description: str,
    correction: str | None,
    on_progress: Callable[[str], None] | None,
    *,
    retry: bool,
) -> tuple[RecipeSpec, dict]:
    spec = await _extract_recipe_spec(_recipe_wizard_messages(description, correction))
    on_progress and on_progress("checking_fixed_structure" if retry else "checking_structure")
    profile = compile_recipe(spec)
    on_progress and on_progress("checking_fixed_recipe" if retry else "checking_recipe")
    semantic_errors = await _semantic_profile_errors(description, profile)
    if semantic_errors:
        raise ValueError("Recipe mismatches:\n- " + "\n- ".join(semantic_errors))
    return spec, profile


async def generate_profile(
    description: str,
    on_progress: Callable[[str], None] | None = None,
) -> dict:
    on_progress and on_progress("generating")
    try:
        _, profile = await _generate_once(description, None, on_progress, retry=False)
        return profile
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as error:
        on_progress and on_progress("repairing")
        correction = (
            "Call submit_recipe_spec again with a complete corrected specification. "
            "Preserve every explicit source value and the source language. "
            f"The previous attempt failed:\n{error}"
        )
        try:
            _, profile = await _generate_once(description, correction, on_progress, retry=True)
            return profile
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as retry_error:
            logger.warning("Recipe wizard returned invalid specification twice: %s", retry_error)
            raise ValueError("Модель не смогла собрать корректный профиль") from retry_error
