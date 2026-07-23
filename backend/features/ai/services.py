"""OpenAI-compatible LLM prompts and server-owned AI conversations."""

import json
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from openai import AsyncOpenAI
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
from features.profiles.services import profile_dict

logger = logging.getLogger(__name__)

AssessmentKind = Literal["brew", "fermentation"]
SubjectType = Literal["brew_session", "fermentation_session", "recipe"]

_MAX_TELEMETRY_POINTS = 48
_MAX_TOOL_ROUNDS = 4
_MAX_LISTED_SESSIONS = 30
_RECENT_MESSAGES = 12
_SUMMARY_TRIGGER_MESSAGES = 24
_PROMPT_VERSION = "v2"
_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


FERMENTATION_SYSTEM_PROMPT = _load_prompt("fermentation.md")
BREW_SYSTEM_PROMPT = _load_prompt("brew.md")
RECIPE_REVIEW_SYSTEM_PROMPT = _load_prompt("recipe_review.md")
RECIPE_REVIEW_DEFAULT = _load_prompt("recipe_review_default.md")
CONVERSATION_SUMMARY_PROMPT = _load_prompt("conversation_summary.md")
DEFAULT_QUESTIONS: dict[str, dict[str, dict[str, str]]] = json.loads(
    _load_prompt("default_questions.json")
)

DEFAULT_INSTRUCTIONS: dict[tuple[AssessmentKind, bool], str] = {
    ("fermentation", False): _load_prompt("fermentation_default_active.md"),
    ("fermentation", True): _load_prompt("fermentation_default_done.md"),
    ("brew", False): _load_prompt("brew_default_active.md"),
    ("brew", True): _load_prompt("brew_default_done.md"),
}

_FOLLOW_UP_SYSTEM_HINT = (
    "For later conversation turns, answer briefly and directly without repeating the full "
    "assessment unless explicitly asked. Reply in the language of the user's latest message."
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_brew_sessions",
            "description": "List locally saved brew sessions, newest first, up to 30.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_fermentation_sessions",
            "description": "List locally saved fermentation sessions, newest first, up to 30.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_sessions",
            "description": "Find past sessions of the same type by name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "A distinctive word or phrase from the session name.",
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
            "description": "Load full local context and telemetry for a session found via search_sessions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "ID returned by a list or search tool.",
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


def _localized_default_question(subject_type: SubjectType, completed: bool, locale: str) -> str:
    language = locale.lower().split("-", 1)[0]
    questions = DEFAULT_QUESTIONS.get(language, DEFAULT_QUESTIONS["en"])
    subject = subject_type.removesuffix("_session")
    state = "default" if subject == "recipe" else ("done" if completed else "active")
    return questions[subject][state]


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


def _subject_settings(db, conversation: AiConversation, locale: str = "ru") -> SubjectSettings:
    if conversation.subject_type == "brew_session":
        completed = not bool(db.get(BrewSession, conversation.subject_id).active)
        return SubjectSettings(
            system_prompt=BREW_SYSTEM_PROMPT,
            context=build_context(db, "brew", conversation.subject_id, None),
            context_tag="current_session_context",
            displayed_default_question=_localized_default_question(
                conversation.subject_type, completed, locale
            ),
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
            displayed_default_question=_localized_default_question(
                conversation.subject_type, completed, locale
            ),
            model_default_instruction=DEFAULT_INSTRUCTIONS[("fermentation", completed)],
            tools=TOOLS,
            current_session_id=conversation.subject_id,
        )
    return SubjectSettings(
        system_prompt=RECIPE_REVIEW_SYSTEM_PROMPT,
        context=build_recipe_context(db, conversation.subject_id),
        context_tag="recipe_context",
        displayed_default_question=_localized_default_question("recipe", False, locale),
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
    system_prompt: str,
    context_tag: str,
    context: str,
    summary: str | None,
    response_locale: str | None = None,
) -> str:
    parts = [
        "[ROLE AND RULES]",
        system_prompt.strip(),
        "",
        "[CURRENT UTC TIME]",
        _utcnow().isoformat(timespec="seconds"),
        "",
        "[CURRENT SUBJECT CONTEXT]",
        "The current data below takes priority over numbers and states mentioned in conversation history.",
        f"<{context_tag}>{context}</{context_tag}>",
        "",
        "[FOLLOW-UP RULE]",
        _FOLLOW_UP_SYSTEM_HINT,
    ]
    if summary:
        parts.extend(["", "[CONVERSATION SUMMARY]", summary.strip()])
    if response_locale:
        parts.extend(
            [
                "",
                "[RESPONSE LOCALE FOR AUTO-GENERATED FIRST TURN]",
                f"Reply using browser locale {response_locale}.",
            ]
        )
    return "\n".join(parts)


def _build_model_messages(
    system_prompt: str,
    context_tag: str,
    context: str,
    summary: str | None,
    history: Sequence[AiMessage],
    user_content: str,
    response_locale: str | None = None,
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": _build_system_block(
                system_prompt, context_tag, context, summary, response_locale
            ),
        },
        *[{"role": message.role, "content": message.content} for message in history],
        {"role": "user", "content": user_content.strip()},
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
    locale: str,
) -> dict:
    with SessionLocal() as db:
        conversation = db.get(AiConversation, conversation_id)
        if conversation is None or not _subject_exists(db, subject_type, subject_id):
            raise LookupError("subject not found")
        settings = _subject_settings(db, conversation, locale)

    assistant_text = await _run_chat_completion(
        _build_model_messages(
            settings.system_prompt,
            settings.context_tag,
            settings.context,
            None,
            (),
            settings.model_default_instruction,
            locale,
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


async def open_conversation(subject_type: SubjectType, subject_id: str, locale: str = "ru") -> dict:
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
        conversation.id, subject_type=subject_type, subject_id=subject_id, locale=locale
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


async def reset_conversation(conversation_id: str, locale: str = "ru") -> dict:
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
        conversation_id, subject_type=subject_type, subject_id=subject_id, locale=locale
    )


async def assess(
    kind: AssessmentKind,
    session_id: str,
    context: str,
    question: str | None,
    history: Sequence[dict[str, str]] = (),
    completed: bool = False,
    locale: str = "ru",
) -> str:
    subject_settings = SubjectSettings(
        system_prompt=FERMENTATION_SYSTEM_PROMPT if kind == "fermentation" else BREW_SYSTEM_PROMPT,
        context=context,
        context_tag="current_session_context",
        displayed_default_question=_localized_default_question(
            "brew_session" if kind == "brew" else "fermentation_session",
            completed,
            locale,
        ),
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
                    locale if question is None else None,
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
    locale: str = "ru",
) -> str:
    prompt = question or RECIPE_REVIEW_DEFAULT
    return await _run_chat_completion(
        [
            {
                "role": "system",
                "content": _build_system_block(
                    RECIPE_REVIEW_SYSTEM_PROMPT,
                    "recipe_context",
                    context,
                    None,
                    locale if question is None else None,
                ),
            },
            *history,
            {"role": "user", "content": prompt},
        ],
        tools=None,
        current_session_id=None,
        temperature=LLM_CHAT_TEMPERATURE if history else LLM_TEMPERATURE,
    )
