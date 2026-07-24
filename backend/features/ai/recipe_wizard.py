"""AI recipe wizard: semantic extraction followed by deterministic profile assembly."""

import json
import logging
from collections.abc import Callable

from openai import BadRequestError
from pydantic import BaseModel, ConfigDict, ValidationError

from core.config import LLM_BASE_URL, LLM_MODEL, LLM_RESPONSE_FORMAT, LLM_TOP_P

from . import services as ai_services
from .beerjson_models import RecipeModel, to_beerjson_document
from .brewzilla_compiler import compile_brewzilla_profile
from .brewzilla_overrides import BrewZillaOverrides, merge_overrides
from .services import _load_prompt, _run_chat_completion

logger = logging.getLogger(__name__)

RECIPE_WIZARD_SYSTEM_PROMPT = _load_prompt("recipe_wizard.md")
RECIPE_WIZARD_VALIDATOR_PROMPT = _load_prompt("recipe_wizard_validator.md")
_VALIDATOR_MAX_RESPONSE_CHARS = 50_000
_VALIDATOR_MAX_TOKENS = 16_384
_VALIDATOR_PREVIEW_CHARS = 300
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
_JSON_OBJECT_RESPONSE_FORMAT = {"type": "json_object"}


class SubmitRecipe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipe: RecipeModel
    brewzilla_overrides: BrewZillaOverrides | None = None


_RECIPE_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_recipe",
        "description": (
            "Submit extracted BeerJSON recipe facts and explicitly requested BrewZilla "
            "process overrides. Deterministic exporters apply defaults and structure."
        ),
        "parameters": SubmitRecipe.model_json_schema(by_alias=True),
    },
}


def _preview(raw: str) -> str:
    compact = " ".join(raw.split())
    if len(compact) > _VALIDATOR_PREVIEW_CHARS:
        compact = f"{compact[:_VALIDATOR_PREVIEW_CHARS]}..."
    return compact


def _validator_response_formats() -> tuple[tuple[str, dict], ...]:
    formats = {
        "json_schema": ("JSON Schema", _RECIPE_WIZARD_VALIDATOR_RESPONSE_FORMAT),
        "json_object": ("JSON mode", _JSON_OBJECT_RESPONSE_FORMAT),
    }
    if LLM_RESPONSE_FORMAT == "auto":
        return formats["json_schema"], formats["json_object"]
    if LLM_RESPONSE_FORMAT == "none":
        return ()
    return (formats[LLM_RESPONSE_FORMAT],)


def _recipe_wizard_messages(description: str, correction: str | None = None) -> list[dict]:
    messages = [
        {"role": "system", "content": RECIPE_WIZARD_SYSTEM_PROMPT.strip()},
        {"role": "user", "content": description.strip()},
    ]
    if correction:
        messages.append({"role": "user", "content": correction})
    return messages


async def _extract_recipe(messages: list[dict]) -> SubmitRecipe:
    request = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": 0,
        "top_p": LLM_TOP_P,
        "tools": [_RECIPE_TOOL],
        "tool_choice": "auto",
    }
    async with ai_services._new_llm_client() as client:
        response = await client.chat.completions.create(**request)

    tool_calls = getattr(response.choices[0].message, "tool_calls", None) or []
    if len(tool_calls) != 1 or tool_calls[0].function.name != "submit_recipe":
        raise ValueError("model must call submit_recipe exactly once")
    try:
        arguments = json.loads(tool_calls[0].function.arguments)
    except json.JSONDecodeError as error:
        raise ValueError("submit_recipe arguments must be valid JSON") from error
    return SubmitRecipe.model_validate(arguments)


def _parse_semantic_validation(raw: str) -> list[str]:
    if len(raw) > _VALIDATOR_MAX_RESPONSE_CHARS:
        raise ValueError(
            f"semantic validator response was too long: {len(raw)} chars; preview={_preview(raw)!r}"
        )
    normalized = raw.strip()
    if normalized.startswith("```"):
        _, _, normalized = normalized.partition("\n")
        if normalized.rstrip().endswith("```"):
            normalized = normalized.rstrip().rsplit("```", 1)[0]
    try:
        result = json.loads(normalized)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"semantic validator returned invalid JSON: preview={_preview(raw)!r}"
        ) from error
    if not isinstance(result, dict):
        raise ValueError(
            f"semantic validator returned non-object JSON: {type(result).__name__}; "
            f"preview={_preview(raw)!r}"
        )
    valid = result.get("valid")
    errors = result.get("errors")
    if (
        not isinstance(valid, bool)
        or not isinstance(errors, list)
        or any(not isinstance(error, str) or not error.strip() for error in errors)
        or valid == bool(errors)
    ):
        raise ValueError(
            f"semantic validator returned invalid shape: valid={valid!r}, errors={errors!r}; "
            f"preview={_preview(raw)!r}"
        )
    return [error.strip() for error in errors]


async def _run_semantic_validator(description: str, submit: SubmitRecipe) -> str:
    messages = [
        {"role": "system", "content": RECIPE_WIZARD_VALIDATOR_PROMPT},
        {
            "role": "user",
            "content": (
                f"<source_description>{description}</source_description>\n"
                f"<candidate_spec>{submit.model_dump_json(by_alias=True, exclude_none=True)}"
                "</candidate_spec>"
            ),
        },
    ]
    request = {
        "tools": None,
        "current_session_id": None,
        "temperature": 0,
        "max_tokens": _VALIDATOR_MAX_TOKENS,
    }
    response_formats = _validator_response_formats()
    for index, (name, response_format) in enumerate(response_formats):
        try:
            return await _run_chat_completion(
                messages,
                response_format=response_format,
                **request,
            )
        except BadRequestError as error:
            if "response_format" not in str(error).lower():
                raise
            fallback_available = index < len(response_formats) - 1 or LLM_RESPONSE_FORMAT == "auto"
            logger.warning(
                "LLM response format is incompatible: model=%s base_url=%s format=%s status=%s; %s",
                LLM_MODEL,
                LLM_BASE_URL,
                name,
                error.status_code,
                "trying the next format" if fallback_available else "no fallback is configured",
            )
            if not fallback_available:
                raise
    if LLM_RESPONSE_FORMAT == "auto":
        logger.warning(
            "LLM supports neither JSON Schema nor JSON mode: model=%s base_url=%s; "
            "retrying semantic validation without response_format",
            LLM_MODEL,
            LLM_BASE_URL,
        )
    return await _run_chat_completion(messages, **request)


async def _semantic_recipe_errors(description: str, submit: SubmitRecipe) -> list[str]:
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            return _parse_semantic_validation(await _run_semantic_validator(description, submit))
        except (json.JSONDecodeError, ValueError) as error:
            last_error = error
            if attempt == 0:
                logger.warning("Recipe wizard semantic validator failed once: %s", error)
            else:
                logger.warning("Recipe wizard semantic validator failed twice: %s", error)
    raise ValueError(
        f"semantic validator returned an invalid result twice: {last_error}"
    ) from last_error


async def _generate_once(
    description: str,
    correction: str | None,
    on_progress: Callable[[str], None] | None,
    *,
    retry: bool,
    user_overrides: BrewZillaOverrides | None,
) -> tuple[SubmitRecipe, dict]:
    submit = await _extract_recipe(_recipe_wizard_messages(description, correction))
    on_progress and on_progress("checking_fixed_structure" if retry else "checking_structure")
    on_progress and on_progress("checking_fixed_recipe" if retry else "checking_recipe")
    semantic_errors = await _semantic_recipe_errors(description, submit)
    if semantic_errors:
        raise ValueError("Recipe mismatches:\n- " + "\n- ".join(semantic_errors))
    overrides = merge_overrides(user_overrides, submit.brewzilla_overrides)
    return submit, compile_brewzilla_profile(submit.recipe, overrides)


async def generate_profile(
    description: str,
    on_progress: Callable[[str], None] | None = None,
    user_overrides: BrewZillaOverrides | None = None,
) -> tuple[dict, dict]:
    on_progress and on_progress("generating")
    try:
        submit, profile = await _generate_once(
            description, None, on_progress, retry=False, user_overrides=user_overrides
        )
        return profile, to_beerjson_document(submit.recipe)
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as error:
        on_progress and on_progress("repairing")
        correction = (
            "Call submit_recipe again with a complete corrected specification. "
            "Preserve every explicit source value and the source language. "
            f"The previous attempt failed:\n{error}"
        )
        try:
            submit, profile = await _generate_once(
                description, correction, on_progress, retry=True, user_overrides=user_overrides
            )
            return profile, to_beerjson_document(submit.recipe)
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as retry_error:
            logger.warning("Recipe wizard returned invalid specification twice: %s", retry_error)
            raise ValueError("Модель не смогла собрать корректный профиль") from retry_error
