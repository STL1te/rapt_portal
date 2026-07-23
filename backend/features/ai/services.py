"""OpenAI-compatible LLM prompts and server-owned AI conversations."""

import json
import logging
import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from openai import AsyncOpenAI
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from core.config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_CHAT_TEMPERATURE,
    LLM_MODEL,
    LLM_TEMPERATURE,
    LLM_TIMEOUT_SECONDS,
    LLM_TOP_P,
)
from core.db import (
    AiConversation,
    AiMessage,
    BrewSession,
    BrewTelemetry,
    HydrometerSession,
    HydrometerTelemetry,
    Profile,
    SessionLocal,
)
from features.brewzillas.services import brew_session_dict
from features.hydrometers.services import session_dict
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
from features.profiles.services import profile_dict

logger = logging.getLogger(__name__)

AssessmentKind = Literal["brew", "fermentation"]
SubjectType = Literal["brew_session", "fermentation_session", "recipe"]

_MAX_TELEMETRY_POINTS = 48
_MAX_TOOL_ROUNDS = 4
_MAX_LISTED_SESSIONS = 30
_RECENT_MESSAGES = 12
_SUMMARY_TRIGGER_MESSAGES = 24
_PROMPT_VERSION = "v1"
_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


FERMENTATION_SYSTEM_PROMPT = _load_prompt("fermentation.md")
BREW_SYSTEM_PROMPT = _load_prompt("brew.md")
RECIPE_REVIEW_SYSTEM_PROMPT = _load_prompt("recipe_review.md")
RECIPE_REVIEW_DEFAULT = _load_prompt("recipe_review_default.md")
RECIPE_REVIEW_DEFAULT_QUESTION = "Проверь рецепт, всё ли с ним ок?"
RECIPE_WIZARD_SYSTEM_PROMPT = _load_prompt("recipe_wizard.md")
CONVERSATION_SUMMARY_PROMPT = _load_prompt("conversation_summary.md")

DEFAULT_QUESTIONS: dict[tuple[AssessmentKind, bool], str] = {
    ("fermentation", False): "Как идёт брожение?",
    ("fermentation", True): "Как прошло брожение?",
    ("brew", False): "Как идёт варка?",
    ("brew", True): "Как прошла варка?",
}

DEFAULT_INSTRUCTIONS: dict[tuple[AssessmentKind, bool], str] = {
    ("fermentation", False): _load_prompt("fermentation_default_active.md"),
    ("fermentation", True): _load_prompt("fermentation_default_done.md"),
    ("brew", False): _load_prompt("brew_default_active.md"),
    ("brew", True): _load_prompt("brew_default_done.md"),
}

_FOLLOW_UP_SYSTEM_HINT = (
    "Если это не первый ход беседы, отвечай коротко и по существу, не повторяй "
    "полный разбор без явной просьбы. Отвечай только на русском языке."
)

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

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_brew_sessions",
            "description": "Список сохранённых локально сессий варки (последние по дате, до 30).",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_fermentation_sessions",
            "description": "Список сохранённых локально сессий брожения (последние по дате, до 30).",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_sessions",
            "description": "Найти прошлые сессии того же типа по названию.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Характерное слово или фраза из названия сессии.",
                    },
                    "kind": {"type": "string", "enum": ["brew", "fermentation"]},
                },
                "required": ["query", "kind"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_session_context",
            "description": "Загрузить полный локальный контекст и телеметрию одной сессии, найденной через search_sessions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "ID, возвращённый инструментом списка или поиска.",
                    },
                    "kind": {"type": "string", "enum": ["brew", "fermentation"]},
                },
                "required": ["session_id", "kind"],
                "additionalProperties": False,
            },
        },
    },
]


@dataclass(frozen=True)
class SubjectSettings:
    system_prompt: str
    context: str
    context_tag: str
    displayed_default_question: str
    model_default_instruction: str
    tools: list[dict] | None
    current_session_id: str | None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _message_dict(message: AiMessage) -> dict:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at,
    }


def _conversation_dict(conversation: AiConversation, messages: Sequence[AiMessage]) -> dict:
    return {
        "id": conversation.id,
        "subject_type": conversation.subject_type,
        "subject_id": conversation.subject_id,
        "model": LLM_MODEL,
        "messages": [_message_dict(message) for message in messages],
    }


def _sample(
    rows: Sequence, fields: tuple[str, ...], count: int = _MAX_TELEMETRY_POINTS
) -> list[dict]:
    selected = (
        rows
        if len(rows) <= count
        else [
            rows[i]
            for i in sorted({round(i * (len(rows) - 1) / (count - 1)) for i in range(count)})
        ]
    )

    def value(item, field):
        v = getattr(item, field)
        return round(v, 1) if isinstance(v, float) else v

    return [{field: value(item, field) for field in fields} for item in selected]


_ROUNDED_SESSION_KEYS = (
    "original_gravity",
    "final_gravity",
    "current_gravity",
    "target_final_gravity",
)


def _fermentation_context(db, session_id: str) -> dict | None:
    session = db.get(HydrometerSession, session_id)
    if not session:
        return None
    telemetry = list(
        db.scalars(
            select(HydrometerTelemetry)
            .where(HydrometerTelemetry.session_id == session_id)
            .order_by(HydrometerTelemetry.timestamp)
        )
    )
    session_data = session_dict(session, db)
    for key in _ROUNDED_SESSION_KEYS:
        if isinstance(session_data.get(key), float):
            session_data[key] = round(session_data[key], 1)
    return {
        "session": session_data,
        "telemetry": _sample(
            telemetry,
            ("timestamp", "gravity", "gravity_velocity", "temperature"),
        ),
    }


def _brew_context(db, session_id: str) -> dict | None:
    session = db.get(BrewSession, session_id)
    if not session:
        return None
    telemetry = list(
        db.scalars(
            select(BrewTelemetry)
            .where(BrewTelemetry.session_id == session_id)
            .order_by(BrewTelemetry.timestamp)
        )
    )
    return {
        "session": brew_session_dict(session),
        "telemetry": _sample(
            telemetry,
            (
                "timestamp",
                "temperature",
                "target_temperature",
                "min_target_temperature",
                "max_target_temperature",
                "control_device_temperature",
                "heating_run_time",
                "heating_starts",
                "auxillary_run_time",
                "auxillary_starts",
                "profile_step_id",
                "profile_step_progress",
                "profile_session_time",
            ),
        ),
    }


def build_context(
    db, kind: AssessmentKind, session_id: str, comparison_session_id: str | None
) -> str:
    build = _fermentation_context if kind == "fermentation" else _brew_context
    current = build(db, session_id)
    if current is None:
        raise LookupError("session not found")

    context: dict[str, object] = {"current_session": current}
    if comparison_session_id:
        comparison = build(db, comparison_session_id)
        if comparison is None:
            raise LookupError("comparison session not found")
        context["comparison_session"] = comparison
    return json.dumps(context, ensure_ascii=False, default=str, separators=(",", ":"))


def build_recipe_context(db, profile_id: str) -> str:
    profile = db.get(Profile, profile_id)
    if profile is None:
        raise LookupError("profile not found")
    return json.dumps(profile_dict(profile), ensure_ascii=False, default=str, separators=(",", ":"))


def _subject_exists(db, subject_type: SubjectType, subject_id: str) -> bool:
    model = {
        "brew_session": BrewSession,
        "fermentation_session": HydrometerSession,
        "recipe": Profile,
    }[subject_type]
    return db.get(model, subject_id) is not None


def _subject_settings(db, conversation: AiConversation) -> SubjectSettings:
    if conversation.subject_type == "brew_session":
        completed = not bool(db.get(BrewSession, conversation.subject_id).active)
        return SubjectSettings(
            system_prompt=BREW_SYSTEM_PROMPT,
            context=build_context(db, "brew", conversation.subject_id, None),
            context_tag="current_session_context",
            displayed_default_question=DEFAULT_QUESTIONS[("brew", completed)],
            model_default_instruction=DEFAULT_INSTRUCTIONS[("brew", completed)],
            tools=TOOLS,
            current_session_id=conversation.subject_id,
        )
    if conversation.subject_type == "fermentation_session":
        completed = not bool(db.get(HydrometerSession, conversation.subject_id).active)
        return SubjectSettings(
            system_prompt=FERMENTATION_SYSTEM_PROMPT,
            context=build_context(db, "fermentation", conversation.subject_id, None),
            context_tag="current_session_context",
            displayed_default_question=DEFAULT_QUESTIONS[("fermentation", completed)],
            model_default_instruction=DEFAULT_INSTRUCTIONS[("fermentation", completed)],
            tools=TOOLS,
            current_session_id=conversation.subject_id,
        )
    return SubjectSettings(
        system_prompt=RECIPE_REVIEW_SYSTEM_PROMPT,
        context=build_recipe_context(db, conversation.subject_id),
        context_tag="recipe_context",
        displayed_default_question=RECIPE_REVIEW_DEFAULT_QUESTION,
        model_default_instruction=RECIPE_REVIEW_DEFAULT,
        tools=None,
        current_session_id=None,
    )


def _load_conversation_messages(db, conversation_id: str) -> list[AiMessage]:
    return list(
        db.scalars(
            select(AiMessage)
            .where(AiMessage.conversation_id == conversation_id)
            .order_by(AiMessage.id)
        )
    )


def _build_system_block(
    system_prompt: str, context_tag: str, context: str, summary: str | None
) -> str:
    parts = [
        "[ROLE AND RULES]",
        system_prompt.strip(),
        "",
        "[CURRENT UTC TIME]",
        _utcnow().isoformat(timespec="seconds"),
        "",
        "[CURRENT SUBJECT CONTEXT]",
        "Актуальные данные ниже имеют приоритет над числами и состояниями, упомянутыми в истории беседы.",
        f"<{context_tag}>{context}</{context_tag}>",
        "",
        "[FOLLOW-UP RULE]",
        _FOLLOW_UP_SYSTEM_HINT,
    ]
    if summary:
        parts.extend(["", "[CONVERSATION SUMMARY]", summary.strip()])
    return "\n".join(parts)


def _build_model_messages(
    system_prompt: str,
    context_tag: str,
    context: str,
    summary: str | None,
    history: Sequence[AiMessage],
    user_content: str,
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": _build_system_block(system_prompt, context_tag, context, summary),
        },
        *[{"role": message.role, "content": message.content} for message in history],
        {"role": "user", "content": user_content.strip()},
    ]


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


def _search_sessions(kind: AssessmentKind, query: str, current_session_id: str) -> list[dict]:
    model = BrewSession if kind == "brew" else HydrometerSession
    with SessionLocal() as db:
        rows = db.scalars(
            select(model)
            .where(func.lower(model.name).contains(query.lower()))
            .order_by(model.start_date.desc())
            .limit(10)
        )
        return [
            {
                "id": session.id,
                "name": session.name,
                "start_date": session.start_date,
                "end_date": session.end_date,
                "is_current": session.id == current_session_id,
            }
            for session in rows
        ]


def _list_sessions(kind: AssessmentKind, current_session_id: str) -> list[dict]:
    model = BrewSession if kind == "brew" else HydrometerSession
    with SessionLocal() as db:
        rows = db.scalars(
            select(model).order_by(model.start_date.desc()).limit(_MAX_LISTED_SESSIONS)
        )
        return [
            {
                "id": session.id,
                "name": session.name,
                "start_date": session.start_date,
                "end_date": session.end_date,
                "active": session.active,
                "is_current": session.id == current_session_id,
            }
            for session in rows
        ]


def _run_tool(current_session_id: str | None, name: str, arguments: dict) -> dict:
    if name == "list_brew_sessions":
        return {"sessions": _list_sessions("brew", current_session_id or "")}
    if name == "list_fermentation_sessions":
        return {"sessions": _list_sessions("fermentation", current_session_id or "")}
    if name == "search_sessions":
        query = str(arguments.get("query", "")).strip()
        kind = arguments.get("kind")
        if kind not in ("brew", "fermentation"):
            return {"error": "kind must be brew or fermentation"}
        if len(query) < 2:
            return {"error": "query must contain at least two characters"}
        return {"sessions": _search_sessions(kind, query, current_session_id or "")}
    if name == "get_session_context":
        session_id = str(arguments.get("session_id", "")).strip()
        kind = arguments.get("kind")
        if kind not in ("brew", "fermentation"):
            return {"error": "kind must be brew or fermentation"}
        if not session_id:
            return {"error": "session_id is required"}
        with SessionLocal() as db:
            context = build_context(db, kind, session_id, None)
        return json.loads(context)
    return {"error": "unknown tool"}


async def _run_chat_completion(
    messages: list[dict],
    *,
    tools: list[dict] | None,
    current_session_id: str | None,
    temperature: float,
    response_format: dict | None = None,
) -> str:
    request: dict = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "top_p": LLM_TOP_P,
    }
    if response_format is not None:
        request["response_format"] = response_format
    if tools:
        request["tools"] = tools
        request["tool_choice"] = "auto"

    async with AsyncOpenAI(
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY,
        timeout=LLM_TIMEOUT_SECONDS,
        max_retries=0,
    ) as client:
        working_messages = list(messages)
        for _ in range(_MAX_TOOL_ROUNDS):
            response = await client.chat.completions.create(**request)
            message = response.choices[0].message
            if not getattr(message, "tool_calls", None):
                return message.content or "Модель не вернула ответ."
            working_messages.append(message.model_dump(exclude_none=True))
            for tool_call in message.tool_calls:
                try:
                    arguments = json.loads(tool_call.function.arguments)
                    result = _run_tool(current_session_id, tool_call.function.name, arguments)
                except (json.JSONDecodeError, LookupError) as error:
                    result = {"error": str(error)}
                working_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    }
                )
            request["messages"] = working_messages
    return "Не удалось завершить поиск контекста для ответа."


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
        return "Заполни description как краткое аккуратное summary рецепта на русском языке."
    if "missing required BrewZilla steps:" in text:
        return (
            "Добавь обязательный BrewZilla-каркас: Mash In, аккуратно названные mash-паузы, "
            "Mash Out, Sparge, Boil, Cooling."
        )
    if "mash-in temperature alert is required" in text:
        return (
            "Добавь в Mash In алерт с trigger='Temperature' на его целевую температуру "
            "и понятным приглашением засыпать солод."
        )
    if "alert" in text and "temperature must be a finite number" in text:
        return (
            "Для алерта с trigger='Temperature' укажи числовое поле temperature. "
            "У Mash In оно должно совпадать с температурой самого шага."
        )
    if "mash-in alert temperature must match step temperature" in text:
        return "В Temperature-alert шага Mash In скопируй точную температуру самого Mash In."
    if "mash-in temperature must be 2-4 degrees above first rest" in text:
        return (
            f"{text}. Установи Mash In на 2–4 °C выше первой температурной паузы "
            "и используй то же значение в его Temperature-alert."
        )
    if "mash-in must wait for manual completion" in text:
        return (
            "Mash In должен держать целевую температуру до ручного подтверждения окончания "
            "засыпи: controlType='Target', endType='Manual', durationType='Manual', length=null."
        )
    if "heating utilisation does not match profile heat power" in text:
        return (
            f"{text}. Исправь конкретно этот шаг: heatingUtilisation должен быть равен "
            "максимальной мощности нагрева, уже указанной в профиле. Она применяется к "
            "Mash In, переходам нагрева и Boil; меньшая мощность — только к выдержкам."
        )
    if "rest must have a separate heating step" in text:
        return (
            "Если мощности нагрева и поддержания различаются, перед каждой паузой добавь "
            "отдельный Target + Temperature шаг нагрева с полной мощностью, затем шаг "
            "выдержки Target + Duration с мощностью поддержания и PID."
        )
    if "boil must not use rest PID" in text:
        return "PID, запрошенный для пауз, не включай на Boil; оставь мощность кипа фиксированной."
    if "alert" in text and "text is required" in text:
        return "У каждого step-alert обязателен непустой alertText с понятным текстом действия."
    if "length must be a positive integer" in text:
        return (
            "Для шагов с controlType='Ramp' или endType='Duration' укажи положительный length в секундах. "
            "Для Mash In и Sparge без длительности используй Target + Manual. Для Cooling используй Target + Temperature."
        )
    if "trigger is invalid" in text:
        return "Для BrewZilla step-alert trigger должен быть одним из: StepStart, StepEnd, Duration, Temperature."
    if "controlType is invalid" in text:
        return "Для BrewZilla используй только controlType='Target' или 'Ramp'."
    if "endType is invalid" in text:
        return "Для BrewZilla используй только endType='Duration', 'Temperature' или 'Manual'."
    if "durationType is invalid" in text:
        return "Используй корректный durationType из разрешённого набора и не оставляй его пустым."
    if "target duration timer must start at temperature" in text:
        return (
            "Для Target-шага с endType='Duration' ставь durationType='Temperature', "
            "чтобы выдержка началась только после достижения целевой температуры."
        )
    if "mash-out temperature must be 78" in text:
        return "Для шага Mash Out используй целевую температуру 78 °C."
    if "alert occurs after step end" in text:
        return "Duration-alert должен срабатывать не позже окончания шага."
    if "fixed profile fields are invalid" in text:
        return (
            "Установи public=false, profile_type_id=null, profile_type_name=null "
            "и корневой alerts=[]."
        )
    if "profile name length is invalid" in text:
        return "Заполни name: от 4 до 50 символов."
    if "profile root must be an object" in text:
        return "Верни один JSON-объект верхнего уровня, а не массив и не markdown."
    return f"Исправь ответ по ошибке валидации: {text}"


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
        if _matches_step_aliases(step_name, _REQUIRED_BREWZILLA_STEPS["Mash In"]) and (
            step.controlType != "Target"
            or step.endType != "Manual"
            or step.durationType != "Manual"
            or step.length is not None
        ):
            raise ValueError(f"step {order} mash-in must wait for manual completion")
        if (
            step.controlType == "Target"
            and step.endType == "Duration"
            and step.durationType != "Temperature"
        ):
            raise ValueError(f"step {order} target duration timer must start at temperature")
        if (
            _matches_step_aliases(step_name, _REQUIRED_BREWZILLA_STEPS["Mash Out"])
            and step.temperature != 78
        ):
            raise ValueError(f"step {order} mash-out temperature must be 78")
        is_mash_in = _matches_step_aliases(step_name, _REQUIRED_BREWZILLA_STEPS["Mash In"])
        is_boil = _matches_step_aliases(step_name, _REQUIRED_BREWZILLA_STEPS["Boil"])
        is_cooling = _matches_step_aliases(step_name, _REQUIRED_BREWZILLA_STEPS["Cooling"])
        is_heat_transition = (
            step.controlType == "Target" and step.endType == "Temperature" and not is_cooling
        )
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
            previous = profile.steps[order - 1] if order > 0 else None
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


async def generate_profile(description: str) -> dict:
    messages = _recipe_wizard_messages(description)
    raw = await _run_chat_completion(
        messages,
        tools=None,
        current_session_id=None,
        temperature=LLM_TEMPERATURE,
        response_format=_RECIPE_WIZARD_RESPONSE_FORMAT,
    )
    try:
        return _validate_generated_profile(raw)
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as error:
        repair_hint = _repair_hint_from_error(error)
        retry_messages = [
            *messages,
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": (
                    "Исправь ответ и верни полный JSON-объект целиком. "
                    "Используй скрытые дефолты RAPT setup, если пользователь не указал иное: "
                    "temperature alerts = yes, sparge = yes, mash-out = yes, whirlpool = no. "
                    "Поле description обязательно: это аккуратное краткое summary рецепта на русском. "
                    "Обязательный BrewZilla-каркас: Mash In, аккуратно названные mash-паузы, "
                    "Mash Out, Sparge, Boil, Cooling. "
                    "Для Target + Duration всегда используй durationType='Temperature'. "
                    "Стандартные параметры: Mash Out 78 °C, Sparge 78 °C, Cooling 20 °C. "
                    "Если в рецепте есть хмель для кипа, добавь Duration-alerts в шаг Boil. "
                    f"Исправление: {repair_hint} "
                    f"Ошибка валидации: {error}"
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
            return _validate_generated_profile(retry_raw)
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as retry_error:
            logger.warning("Recipe wizard returned invalid profile twice: %s", retry_error)
            raise ValueError("Модель не смогла собрать корректный профиль") from retry_error


async def _summarize_messages(existing_summary: str | None, messages: Sequence[AiMessage]) -> str:
    history_lines: list[str] = []
    if existing_summary:
        history_lines.extend(["[PREVIOUS SUMMARY]", existing_summary.strip(), ""])
    history_lines.append("[MESSAGES]")
    for message in messages:
        history_lines.append(f"{message.role}: {message.content}")
    summary_messages = [
        {"role": "system", "content": CONVERSATION_SUMMARY_PROMPT},
        {"role": "user", "content": "\n".join(history_lines)},
    ]
    return await _run_chat_completion(
        summary_messages,
        tools=None,
        current_session_id=None,
        temperature=LLM_CHAT_TEMPERATURE,
    )


async def _maybe_summarize_conversation(
    db,
    conversation: AiConversation,
) -> tuple[str | None, list[AiMessage]]:
    unsummarized = list(
        db.scalars(
            select(AiMessage)
            .where(AiMessage.conversation_id == conversation.id)
            .where(AiMessage.id > (conversation.summary_through_message_id or 0))
            .order_by(AiMessage.id)
        )
    )
    if len(unsummarized) <= _SUMMARY_TRIGGER_MESSAGES:
        return conversation.summary, unsummarized

    older_messages = unsummarized[:-_RECENT_MESSAGES]
    recent_messages = unsummarized[-_RECENT_MESSAGES:]
    try:
        summary = await _summarize_messages(conversation.summary, older_messages)
    except Exception:
        logger.warning("AI conversation summary failed for %s", conversation.id, exc_info=True)
        return conversation.summary, unsummarized[-_SUMMARY_TRIGGER_MESSAGES:]

    conversation.summary = summary
    conversation.summary_through_message_id = older_messages[-1].id
    return summary, recent_messages


def _create_conversation(db, subject_type: SubjectType, subject_id: str) -> AiConversation:
    now = _utcnow()
    conversation = AiConversation(
        id=str(uuid.uuid4()),
        subject_type=subject_type,
        subject_id=subject_id,
        prompt_version=_PROMPT_VERSION,
        summary=None,
        summary_through_message_id=None,
        created_at=now,
        updated_at=now,
    )
    db.add(conversation)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(AiConversation).where(
                AiConversation.subject_type == subject_type,
                AiConversation.subject_id == subject_id,
            )
        )
        if existing is None:
            raise
        return existing
    db.refresh(conversation)
    return conversation


async def _bootstrap_conversation(
    conversation_id: str,
    *,
    subject_type: SubjectType,
    subject_id: str,
) -> dict:
    with SessionLocal() as db:
        conversation = db.get(AiConversation, conversation_id)
        if conversation is None or not _subject_exists(db, subject_type, subject_id):
            raise LookupError("subject not found")
        settings = _subject_settings(db, conversation)

    assistant_text = await _run_chat_completion(
        _build_model_messages(
            settings.system_prompt,
            settings.context_tag,
            settings.context,
            None,
            (),
            settings.model_default_instruction,
        ),
        tools=settings.tools,
        current_session_id=settings.current_session_id,
        temperature=LLM_TEMPERATURE,
    )

    with SessionLocal() as db:
        conversation = db.get(AiConversation, conversation.id)
        if conversation is None or not _subject_exists(db, subject_type, subject_id):
            raise LookupError("subject not found")
        messages = _load_conversation_messages(db, conversation.id)
        if messages:
            return _conversation_dict(conversation, messages)
        now = _utcnow()
        user_message = AiMessage(
            conversation_id=conversation.id,
            role="user",
            content=settings.displayed_default_question,
            created_at=now,
        )
        assistant_message = AiMessage(
            conversation_id=conversation.id,
            role="assistant",
            content=assistant_text,
            created_at=now,
        )
        conversation.updated_at = now
        db.add_all([user_message, assistant_message])
        db.commit()
        db.refresh(user_message)
        db.refresh(assistant_message)
        return _conversation_dict(conversation, [user_message, assistant_message])


async def open_conversation(subject_type: SubjectType, subject_id: str) -> dict:
    with SessionLocal() as db:
        if not _subject_exists(db, subject_type, subject_id):
            raise LookupError("subject not found")
        conversation = db.scalar(
            select(AiConversation).where(
                AiConversation.subject_type == subject_type,
                AiConversation.subject_id == subject_id,
            )
        )
        if conversation is None:
            conversation = _create_conversation(db, subject_type, subject_id)
        messages = _load_conversation_messages(db, conversation.id)
        if messages:
            return _conversation_dict(conversation, messages)
    return await _bootstrap_conversation(
        conversation.id, subject_type=subject_type, subject_id=subject_id
    )


async def send_conversation_message(conversation_id: str, content: str) -> dict:
    stripped = content.strip()
    if not stripped:
        raise ValueError("content is required")

    with SessionLocal() as db:
        conversation = db.get(AiConversation, conversation_id)
        if conversation is None:
            raise LookupError("conversation not found")
        if not _subject_exists(db, conversation.subject_type, conversation.subject_id):
            raise LookupError("subject not found")
        settings = _subject_settings(db, conversation)
        summary, history = await _maybe_summarize_conversation(db, conversation)
        db.commit()

    assistant_text = await _run_chat_completion(
        _build_model_messages(
            settings.system_prompt,
            settings.context_tag,
            settings.context,
            summary,
            history,
            stripped,
        ),
        tools=settings.tools,
        current_session_id=settings.current_session_id,
        temperature=LLM_CHAT_TEMPERATURE,
    )

    with SessionLocal() as db:
        conversation = db.get(AiConversation, conversation_id)
        if conversation is None:
            raise LookupError("conversation not found")
        if not _subject_exists(db, conversation.subject_type, conversation.subject_id):
            raise LookupError("subject not found")
        now = _utcnow()
        user_message = AiMessage(
            conversation_id=conversation.id,
            role="user",
            content=stripped,
            created_at=now,
        )
        assistant_message = AiMessage(
            conversation_id=conversation.id,
            role="assistant",
            content=assistant_text,
            created_at=now,
        )
        conversation.updated_at = now
        db.add_all([user_message, assistant_message])
        db.commit()
        db.refresh(user_message)
        db.refresh(assistant_message)
        return {
            "user_message": _message_dict(user_message),
            "assistant_message": _message_dict(assistant_message),
            "model": LLM_MODEL,
        }


async def reset_conversation(conversation_id: str) -> dict:
    with SessionLocal() as db:
        conversation = db.get(AiConversation, conversation_id)
        if conversation is None:
            raise LookupError("conversation not found")
        if not _subject_exists(db, conversation.subject_type, conversation.subject_id):
            raise LookupError("subject not found")
        subject_type = conversation.subject_type
        subject_id = conversation.subject_id
        db.execute(delete(AiMessage).where(AiMessage.conversation_id == conversation_id))
        conversation.summary = None
        conversation.summary_through_message_id = None
        conversation.updated_at = _utcnow()
        db.commit()
    return await _bootstrap_conversation(
        conversation_id, subject_type=subject_type, subject_id=subject_id
    )


async def assess(
    kind: AssessmentKind,
    session_id: str,
    context: str,
    question: str | None,
    history: Sequence[dict[str, str]] = (),
    completed: bool = False,
) -> str:
    subject_settings = SubjectSettings(
        system_prompt=FERMENTATION_SYSTEM_PROMPT if kind == "fermentation" else BREW_SYSTEM_PROMPT,
        context=context,
        context_tag="current_session_context",
        displayed_default_question=DEFAULT_QUESTIONS[(kind, completed)],
        model_default_instruction=DEFAULT_INSTRUCTIONS[(kind, completed)],
        tools=TOOLS,
        current_session_id=session_id,
    )
    prompt = question or subject_settings.model_default_instruction
    return await _run_chat_completion(
        [
            {
                "role": "system",
                "content": _build_system_block(
                    subject_settings.system_prompt,
                    subject_settings.context_tag,
                    subject_settings.context,
                    None,
                ),
            },
            *history,
            {"role": "user", "content": prompt},
        ],
        tools=subject_settings.tools,
        current_session_id=session_id,
        temperature=LLM_CHAT_TEMPERATURE if history else LLM_TEMPERATURE,
    )


async def review_recipe(
    context: str,
    question: str | None,
    history: Sequence[dict[str, str]] = (),
) -> str:
    prompt = question or RECIPE_REVIEW_DEFAULT
    return await _run_chat_completion(
        [
            {
                "role": "system",
                "content": _build_system_block(
                    RECIPE_REVIEW_SYSTEM_PROMPT, "recipe_context", context, None
                ),
            },
            *history,
            {"role": "user", "content": prompt},
        ],
        tools=None,
        current_session_id=None,
        temperature=LLM_CHAT_TEMPERATURE if history else LLM_TEMPERATURE,
    )
