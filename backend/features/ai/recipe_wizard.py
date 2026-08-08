"""AI recipe wizard: semantic extraction followed by deterministic profile assembly."""

import json
import logging
import re
from collections.abc import Callable

from openai import BadRequestError
from pydantic import BaseModel, ConfigDict, ValidationError

from core.config import WIZARD_LLM

from .beerjson_models import RecipeModel, to_beerjson_document
from .brewzilla_compiler import compile_brewzilla_profile
from .brewzilla_overrides import BrewZillaOverrides, merge_overrides
from .services import _load_prompt, _run_chat_completion

logger = logging.getLogger(__name__)

RECIPE_WIZARD_SYSTEM_PROMPT = _load_prompt("recipe_wizard.md")
_VALIDATOR_PROMPT_RAW = _load_prompt("recipe_wizard_validator.md")
_INVENTION_BLOCK = "<!-- inventions:start -->"
# Two judges, two contracts. Against a real source, a value the source never states is a
# fabrication worth rejecting. Against a hand-typed free-form DRAFT (freeform_rewrite.py)
# it is not: partial drafts deliberately omit sections while the target spec keeps them,
# so the invention rule rejected every partial rewrite (26/26) and half the full ones.
# There the only question is whether the rewrite LOST a value.
RECIPE_WIZARD_VALIDATOR_PROMPT = _VALIDATOR_PROMPT_RAW.replace(_INVENTION_BLOCK, "").replace(
    "<!-- inventions:end -->", ""
)
RECIPE_WIZARD_VALIDATOR_PROMPT_OMISSIONS_ONLY = re.sub(
    r"<!-- inventions:start -->.*?<!-- inventions:end -->\n*",
    "",
    _VALIDATOR_PROMPT_RAW,
    flags=re.DOTALL,
)
_VALIDATOR_MAX_RESPONSE_CHARS = 50_000
# Ceiling, not an allocation. 16k truncated long recipes on reasoning teachers:
# thinking tokens share this budget with the pretty-printed JSON answer.
_MAX_COMPLETION_TOKENS = 32_768
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
                    # no string length bounds: llama.cpp grammar conversion fails on them
                    "items": {"type": "string"},
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


def _response_schema(schema):
    """Normalize the Pydantic schema for response_format backends: llama.cpp fails to
    build a grammar from string length bounds, and OpenAI-style strict mode requires
    every property to be listed in `required` (optional fields stay nullable) and
    rejects `default`. Pydantic still enforces the full contract server-side."""
    if isinstance(schema, dict):
        cleaned = {
            key: _response_schema(value)
            for key, value in schema.items()
            if key not in ("minLength", "maxLength", "default")
        }
        if "properties" in cleaned:
            cleaned["required"] = list(cleaned["properties"])
        return cleaned
    if isinstance(schema, list):
        return [_response_schema(value) for value in schema]
    return schema


# Local backends (Ollama, LM Studio) enforce response_format with grammar-constrained
# decoding but do NOT constrain tool-call arguments, so extraction uses response_format.
_RECIPE_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "submit_recipe",
        "strict": True,
        "schema": _response_schema(SubmitRecipe.model_json_schema(by_alias=True)),
    },
}


def _preview(raw: str) -> str:
    compact = " ".join(raw.split())
    if len(compact) > _VALIDATOR_PREVIEW_CHARS:
        compact = f"{compact[:_VALIDATOR_PREVIEW_CHARS]}..."
    return compact


def _response_format_fallbacks(schema_format: dict) -> tuple[tuple[str, dict], ...]:
    formats = {
        "json_schema": ("JSON Schema", schema_format),
        "json_object": ("JSON mode", _JSON_OBJECT_RESPONSE_FORMAT),
    }
    if WIZARD_LLM.response_format == "auto":
        return formats["json_schema"], formats["json_object"]
    if WIZARD_LLM.response_format == "none":
        return ()
    return (formats[WIZARD_LLM.response_format],)


def _strip_code_fences(raw: str) -> str:
    normalized = raw.strip()
    if normalized.startswith("```"):
        _, _, normalized = normalized.partition("\n")
        if normalized.rstrip().endswith("```"):
            normalized = normalized.rstrip().rsplit("```", 1)[0]
    return normalized


async def _run_json_completion(
    messages: list[dict],
    schema_format: dict,
    *,
    max_tokens: int | None = None,
    model: str | None = None,
) -> str:
    request = {
        "llm": WIZARD_LLM,
        "tools": None,
        "current_session_id": None,
        "temperature": 0,
        "max_tokens": max_tokens,
        "model": model,
    }
    response_formats = _response_format_fallbacks(schema_format)
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
            logger.error(error)
            fallback_available = (
                index < len(response_formats) - 1 or WIZARD_LLM.response_format == "auto"
            )
            logger.warning(
                "LLM response format is incompatible: model=%s base_url=%s format=%s status=%s; %s",
                WIZARD_LLM.model,
                WIZARD_LLM.base_url,
                name,
                error.status_code,
                "trying the next format" if fallback_available else "no fallback is configured",
            )
            if not fallback_available:
                raise
    if WIZARD_LLM.response_format == "auto":
        logger.warning(
            "LLM supports neither JSON Schema nor JSON mode: model=%s base_url=%s; "
            "retrying without response_format",
            WIZARD_LLM.model,
            WIZARD_LLM.base_url,
        )
    return await _run_chat_completion(messages, **request)


def _recipe_wizard_messages(description: str, correction: str | None = None) -> list[dict]:
    messages = [
        {"role": "system", "content": RECIPE_WIZARD_SYSTEM_PROMPT.strip()},
        {"role": "user", "content": description.strip()},
    ]
    if correction:
        messages.append({"role": "user", "content": correction})
    return messages


def _strip_empty_strings(node):
    """Drop the placeholders a constrained decoder emits for "nothing to say here":
    "" for a forced optional key (minLength never reaches the grammar) and a null list
    element for an empty list. Removing them restores the object pydantic expects.
    A null *value* is kept - for a nullable field it is the honest answer."""
    if isinstance(node, dict):
        return {
            key: _strip_empty_strings(value) for key, value in node.items() if value != ""
        }
    if isinstance(node, list):
        return [_strip_empty_strings(value) for value in node if value is not None]
    return node


async def _extract_recipe(messages: list[dict]) -> SubmitRecipe:
    raw = await _run_json_completion(
        messages, _RECIPE_RESPONSE_FORMAT, max_tokens=_MAX_COMPLETION_TOKENS
    )
    try:
        arguments = json.loads(_strip_code_fences(raw))
    except json.JSONDecodeError as error:
        raise ValueError(
            f"submit_recipe must be a single valid JSON object: preview={_preview(raw)!r}"
        ) from error
    return SubmitRecipe.model_validate(_strip_empty_strings(arguments))


def _parse_semantic_validation(raw: str) -> list[str]:
    if len(raw) > _VALIDATOR_MAX_RESPONSE_CHARS:
        raise ValueError(
            f"semantic validator response was too long: {len(raw)} chars; preview={_preview(raw)!r}"
        )
    try:
        result = json.loads(_strip_code_fences(raw))
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


async def _run_semantic_validator(
    description: str, submit: SubmitRecipe, *, check_inventions: bool = True
) -> str:
    messages = [
        {
            "role": "system",
            "content": (
                RECIPE_WIZARD_VALIDATOR_PROMPT
                if check_inventions
                else RECIPE_WIZARD_VALIDATOR_PROMPT_OMISSIONS_ONLY
            ),
        },
        {
            "role": "user",
            "content": (
                f"<source_description>{description}</source_description>\n"
                f"<candidate_spec>{submit.model_dump_json(by_alias=True, exclude_none=True)}"
                "</candidate_spec>"
            ),
        },
    ]
    return await _run_json_completion(
        messages,
        _RECIPE_WIZARD_VALIDATOR_RESPONSE_FORMAT,
        max_tokens=_MAX_COMPLETION_TOKENS,
        model=WIZARD_LLM.validator_model,
    )


async def _semantic_recipe_errors(
    description: str, submit: SubmitRecipe, *, check_inventions: bool = True
) -> list[str]:
    """Compare `submit` against `description`. `check_inventions=False` drops the
    fabrication half of the contract - use it when `description` is a free-form draft that
    is allowed to omit what the spec keeps (see the prompt constants above)."""
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            return _parse_semantic_validation(
                await _run_semantic_validator(
                    description, submit, check_inventions=check_inventions
                )
            )
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
) -> tuple[SubmitRecipe, dict, list[str]]:
    submit = await _extract_recipe(_recipe_wizard_messages(description, correction))
    on_progress and on_progress("checking_fixed_structure" if retry else "checking_structure")
    on_progress and on_progress("checking_fixed_recipe" if retry else "checking_recipe")
    semantic_errors = await _semantic_recipe_errors(description, submit)
    overrides = merge_overrides(user_overrides, submit.brewzilla_overrides)
    profile = compile_brewzilla_profile(submit.recipe, overrides)
    return submit, profile, semantic_errors


async def generate_profile(
    description: str,
    on_progress: Callable[[str], None] | None = None,
    user_overrides: BrewZillaOverrides | None = None,
) -> tuple[dict, dict]:
    on_progress and on_progress("generating")
    try:
        submit, profile, semantic_errors = await _generate_once(
            description, None, on_progress, retry=False, user_overrides=user_overrides
        )
        if semantic_errors:
            raise ValueError("Recipe mismatches:\n- " + "\n- ".join(semantic_errors))
        return profile, to_beerjson_document(submit.recipe)
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as error:
        on_progress and on_progress("repairing")
        correction = (
            "Return submit_recipe again as one complete corrected JSON object. "
            "Preserve every explicit source value and the source language. "
            f"The previous attempt failed:\n{error}"
        )
        try:
            submit, profile, semantic_errors = await _generate_once(
                description, correction, on_progress, retry=True, user_overrides=user_overrides
            )
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as retry_error:
            logger.warning("Recipe wizard returned invalid specification twice: %s", retry_error)
            raise ValueError("Модель не смогла собрать корректный профиль") from retry_error
        if semantic_errors:
            # Extraction succeeded but the repaired recipe still doesn't clear semantic
            # validation; hand back the imperfect profile anyway so the user can adjust
            # it themselves instead of getting a dead end.
            logger.warning(
                "Recipe wizard accepted a profile with unresolved mismatches: %s",
                semantic_errors,
            )
        return profile, to_beerjson_document(submit.recipe)
