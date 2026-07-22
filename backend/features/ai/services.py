"""OpenAI-compatible LLM prompts and local-session context builders."""

import json
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from openai import AsyncOpenAI
from sqlalchemy import func, select

from core.config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_CHAT_TEMPERATURE,
    LLM_MODEL,
    LLM_TEMPERATURE,
    LLM_TIMEOUT_SECONDS,
    LLM_TOP_P,
)
from core.db import BrewSession, BrewTelemetry, HydrometerSession, HydrometerTelemetry, SessionLocal
from features.brewzillas.services import brew_session_dict
from features.hydrometers.services import session_dict

AssessmentKind = Literal["brew", "fermentation"]
_MAX_TELEMETRY_POINTS = 48
_MAX_TOOL_ROUNDS = 4
_MAX_LISTED_SESSIONS = 30
_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


FERMENTATION_SYSTEM_PROMPT = _load_prompt("fermentation.md")
BREW_SYSTEM_PROMPT = _load_prompt("brew.md")

# Короткий вопрос, который фронт показывает в чате как реплику пользователя.
# Ключ — (тип сессии, завершена ли она): у активной и прошедшей сессии разный текст.
DEFAULT_QUESTIONS: dict[tuple[AssessmentKind, bool], str] = {
    ("fermentation", False): "Как идёт брожение?",
    ("fermentation", True): "Как прошло брожение?",
    ("brew", False): "Как идёт варка?",
    ("brew", True): "Как прошла варка?",
}

# Что реально уходит в модель на дефолтный запрос — фронт показывает короткий
# DEFAULT_QUESTIONS, а модель получает эту директиву, чтобы не переспрашивать.
# Для активной сессии — оценка «сейчас», для завершённой — ретроспективный разбор.
DEFAULT_INSTRUCTIONS: dict[tuple[AssessmentKind, bool], str] = {
    ("fermentation", False): _load_prompt("fermentation_default_active.md"),
    ("fermentation", True): _load_prompt("fermentation_default_done.md"),
    ("brew", False): _load_prompt("brew_default_active.md"),
    ("brew", True): _load_prompt("brew_default_done.md"),
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


def is_session_completed(db, kind: AssessmentKind, session_id: str) -> bool:
    model = BrewSession if kind == "brew" else HydrometerSession
    session = db.get(model, session_id)
    return bool(session and not session.active)


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


def _run_tool(current_session_id: str, name: str, arguments: dict) -> dict:
    if name == "list_brew_sessions":
        return {"sessions": _list_sessions("brew", current_session_id)}
    if name == "list_fermentation_sessions":
        return {"sessions": _list_sessions("fermentation", current_session_id)}
    if name == "search_sessions":
        query = str(arguments.get("query", "")).strip()
        kind = arguments.get("kind")
        if kind not in ("brew", "fermentation"):
            return {"error": "kind must be brew or fermentation"}
        if len(query) < 2:
            return {"error": "query must contain at least two characters"}
        return {"sessions": _search_sessions(kind, query, current_session_id)}
    if name == "get_session_context":
        session_id = str(arguments.get("session_id", ""))
        kind = arguments.get("kind")
        if kind not in ("brew", "fermentation"):
            return {"error": "kind must be brew or fermentation"}
        with SessionLocal() as db:
            context = build_context(db, kind, session_id, None)
        return json.loads(context)
    return {"error": "unknown tool"}


async def assess(
    kind: AssessmentKind,
    session_id: str,
    context: str,
    question: str | None,
    history: Sequence[dict[str, str]] = (),
    completed: bool = False,
) -> str:
    prompt = question or DEFAULT_INSTRUCTIONS[(kind, completed)]
    # После первой оценки (в истории уже есть реплики) отвечаем свободнее.
    temperature = LLM_CHAT_TEMPERATURE if history else LLM_TEMPERATURE
    system_prompt = FERMENTATION_SYSTEM_PROMPT if kind == "fermentation" else BREW_SYSTEM_PROMPT
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        *history,
        {
            "role": "user",
            "content": (
                f"Текущее время (UTC): {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n"
                f"Запрос: {prompt}\n\n"
                f"<current_session_context>{context}</current_session_context>\n\n"
                "Ответь только на русском языке."
            ),
        },
    ]
    async with AsyncOpenAI(
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY,
        timeout=LLM_TIMEOUT_SECONDS,
        max_retries=0,
    ) as client:
        for _ in range(_MAX_TOOL_ROUNDS):
            response = await client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=temperature,
                top_p=LLM_TOP_P,
            )
            message = response.choices[0].message
            if not message.tool_calls:
                return message.content or "Модель не вернула ответ."
            messages.append(message.model_dump(exclude_none=True))
            for tool_call in message.tool_calls:
                try:
                    arguments = json.loads(tool_call.function.arguments)
                    result = _run_tool(session_id, tool_call.function.name, arguments)
                except (json.JSONDecodeError, LookupError) as error:
                    result = {"error": str(error)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    }
                )
    return "Не удалось завершить поиск контекста для ответа."
