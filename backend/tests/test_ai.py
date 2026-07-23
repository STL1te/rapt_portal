"""Offline checks for the OpenAI-compatible AI workflow."""

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import LLM_CHAT_TEMPERATURE, LLM_TEMPERATURE
from core.db import (
    AiConversation,
    AiMessage,
    Base,
    BrewSession,
    BrewTelemetry,
    HydrometerSession,
    HydrometerTelemetry,
    Profile,
)
from features.ai.recipe_wizard import RecipeSpec, compile_recipe, generate_profile
from features.ai.router import RecipeWizardRequest, recipe_wizard_stream_endpoint
from features.ai.services import (
    _RECENT_MESSAGES,
    _SUMMARY_TRIGGER_MESSAGES,
    DEFAULT_INSTRUCTIONS,
    _localized_default_question,
    _sample,
    open_conversation,
    reset_conversation,
    send_conversation_message,
)


def _message(content=None, *, tool_calls=None):
    def dump(**_):
        data = {"role": "assistant"}
        if content is not None:
            data["content"] = content
        if tool_calls:
            data["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in tool_calls
            ]
        return data

    return SimpleNamespace(content=content, tool_calls=tool_calls, model_dump=dump)


class _FakeOpenAIClient:
    def __init__(self, factory, responses):
        self.chat = SimpleNamespace(completions=self)
        self._factory = factory
        self._responses = list(responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def create(self, **kwargs):
        self._factory.requests.append(kwargs)
        message = self._responses.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _FakeOpenAIFactory:
    def __init__(self, plans):
        self._plans = [list(plan) for plan in plans]
        self.requests = []

    def __call__(self, **_kwargs):
        return _FakeOpenAIClient(self, self._plans.pop(0))


class _TestDb:
    def __init__(self):
        handle, path = tempfile.mkstemp(suffix=".db")
        self._path = path
        self._handle = handle
        self.url = f"sqlite:///{self._path}"
        self.engine = sa.create_engine(self.url, future=True)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)
        Base.metadata.create_all(self.engine)

    def close(self):
        self.engine.dispose()
        os.close(self._handle)
        Path(self._path).unlink(missing_ok=True)


def _seed_db(session_factory):
    now = datetime(2026, 7, 23, 12, 0, 0)
    with session_factory() as db:
        db.add(
            BrewSession(
                id="brew-1",
                brewzilla_id="bz-1",
                name="Tropicana IPA",
                profile_id=None,
                profile_json=json.dumps({"steps": []}, ensure_ascii=False),
                start_date=now - timedelta(hours=1),
                end_date=None,
                active=True,
            )
        )
        db.add(
            BrewTelemetry(
                session_id="brew-1",
                timestamp=now,
                temperature=65.0,
                target_temperature=66.0,
                min_target_temperature=65.0,
                max_target_temperature=67.0,
                control_device_temperature=64.4,
                heating_run_time=120.0,
                heating_starts=2,
                auxillary_run_time=60.0,
                auxillary_starts=1,
                profile_step_id=None,
                profile_step_progress=0.4,
                profile_session_time=1800.0,
                rssi=-80.0,
            )
        )
        db.add(
            HydrometerSession(
                id="ferm-1",
                hydrometer_id="hydro-1",
                name="NEIPA fermentation",
                yeast_id=None,
                start_date=now - timedelta(days=3),
                end_date=None,
                original_gravity=1054.0,
                final_gravity=1012.0,
                active=True,
            )
        )
        db.add(
            HydrometerTelemetry(
                session_id="ferm-1",
                timestamp=now,
                gravity=1018.0,
                gravity_velocity=-1.2,
                temperature=20.0,
                battery=90.0,
                rssi=-75.0,
            )
        )
        db.add(
            Profile(
                id="recipe-1",
                name="Русский стаут",
                description="Тестовый рецепт",
                public=False,
                rating=None,
                profile_type_id="brew",
                profile_type_name="Brew",
                steps_json=json.dumps(
                    [{"id": "step-1", "name": "Mash", "order": 0, "alerts": []}],
                    ensure_ascii=False,
                ),
                alerts_json="[]",
                archived=False,
                draft=False,
                updated_at=now,
            )
        )
        db.commit()


def _count_messages(session_factory, conversation_id: str) -> int:
    with session_factory() as db:
        return len(
            list(
                db.scalars(
                    sa.select(AiMessage)
                    .where(AiMessage.conversation_id == conversation_id)
                    .order_by(AiMessage.id)
                )
            )
        )


_VALID_WIZARD_JSON = json.dumps(
    {
        "name": "APA 23 л",
        "description": "Одноступенчатое затирание и кип 60 минут",
        "public": False,
        "profile_type_id": None,
        "profile_type_name": None,
        "steps": [
            {
                "id": None,
                "name": "Mash In",
                "order": 7,
                "controlType": "Target",
                "endType": "Manual",
                "durationType": "Manual",
                "operator": None,
                "length": None,
                "temperature": 69.0,
                "minTemperature": None,
                "maxTemperature": None,
                "gravity": None,
                "pumpEnabled": None,
                "pumpUtilisation": None,
                "heatingUtilisation": None,
                "pidEnabled": None,
                "sensorDifferential": None,
                "alerts": [
                    {
                        "id": None,
                        "alertText": "Засыпать солод",
                        "trigger": "Temperature",
                        "operator": None,
                        "temperature": 69.0,
                        "gravity": None,
                        "length": None,
                    }
                ],
            },
            {
                "id": None,
                "name": "Мальтозная пауза",
                "order": 8,
                "controlType": "Target",
                "endType": "Duration",
                "durationType": "Temperature",
                "operator": None,
                "length": 3600,
                "temperature": 67.0,
                "minTemperature": None,
                "maxTemperature": None,
                "gravity": None,
                "pumpEnabled": None,
                "pumpUtilisation": None,
                "heatingUtilisation": None,
                "pidEnabled": None,
                "sensorDifferential": None,
                "alerts": [],
            },
            {
                "id": None,
                "name": "Mash Out",
                "order": 2,
                "controlType": "Target",
                "endType": "Duration",
                "durationType": "Temperature",
                "operator": None,
                "length": 600,
                "temperature": 78.0,
                "minTemperature": None,
                "maxTemperature": None,
                "gravity": None,
                "pumpEnabled": None,
                "pumpUtilisation": None,
                "heatingUtilisation": None,
                "pidEnabled": None,
                "sensorDifferential": None,
                "alerts": [],
            },
            {
                "id": None,
                "name": "Sparge",
                "order": 3,
                "controlType": "Target",
                "endType": "Manual",
                "durationType": "Manual",
                "operator": None,
                "length": None,
                "temperature": 78.0,
                "minTemperature": None,
                "maxTemperature": None,
                "gravity": None,
                "pumpEnabled": None,
                "pumpUtilisation": None,
                "heatingUtilisation": None,
                "pidEnabled": None,
                "sensorDifferential": None,
                "alerts": [],
            },
            {
                "id": None,
                "name": "Boil",
                "order": 9,
                "controlType": "Target",
                "endType": "Duration",
                "durationType": "Temperature",
                "operator": None,
                "length": 3600,
                "temperature": 100.0,
                "minTemperature": None,
                "maxTemperature": None,
                "gravity": None,
                "pumpEnabled": None,
                "pumpUtilisation": None,
                "heatingUtilisation": None,
                "pidEnabled": None,
                "sensorDifferential": None,
                "alerts": [
                    {
                        "id": None,
                        "alertText": "Добавить хмель — до конца кипа 15 минут",
                        "trigger": "Duration",
                        "operator": None,
                        "temperature": None,
                        "gravity": None,
                        "length": 2700,
                    }
                ],
            },
            {
                "id": None,
                "name": "Cooling",
                "order": 10,
                "controlType": "Target",
                "endType": "Temperature",
                "durationType": "Temperature",
                "operator": None,
                "length": None,
                "temperature": 20.0,
                "minTemperature": None,
                "maxTemperature": None,
                "gravity": None,
                "pumpEnabled": None,
                "pumpUtilisation": None,
                "heatingUtilisation": None,
                "pidEnabled": None,
                "sensorDifferential": None,
                "alerts": [],
            },
        ],
        "alerts": [],
    },
    ensure_ascii=False,
)
_VALID_SEMANTIC_VALIDATION = '{"valid":true,"errors":[]}'
_VALID_RECIPE_SPEC = {
    "name": "APA 23 л",
    "description": "Одноступенчатое затирание и кип 60 минут",
    "mash_in_temperature_c": 69,
    "mash_in_alert_text": "Засыпать солод",
    "mash_rests": [
        {
            "name": "Мальтозная пауза",
            "temperature_c": 67,
            "duration_seconds": 3600,
        }
    ],
    "heat_power_pct": None,
    "rest_power_pct": None,
    "mash_pid_enabled": False,
    "mash_out_duration_seconds": 600,
    "boil_temperature_c": 100,
    "boil_duration_seconds": 3600,
    "boil_additions": [
        {
            "text": "Добавить хмель — до конца кипа 15 минут",
            "timing_reference": "before_end",
            "offset_seconds": 900,
        }
    ],
    "whirlpool": None,
    "cooling_temperature_c": 20,
}


def _recipe_spec_message(spec=None):
    call = SimpleNamespace(
        id="recipe-call",
        function=SimpleNamespace(
            name="submit_recipe_spec",
            arguments=json.dumps(spec or _VALID_RECIPE_SPEC, ensure_ascii=False),
        ),
    )
    return _message(tool_calls=[call])


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


@pytest.fixture
def db(monkeypatch):
    """Fresh seeded SQLite DB with services.SessionLocal pointed at it."""
    test_db = _TestDb()
    _seed_db(test_db.SessionLocal)
    monkeypatch.setattr("features.ai.services.SessionLocal", test_db.SessionLocal)
    try:
        yield test_db
    finally:
        test_db.close()


@pytest.fixture
def install_llm(monkeypatch):
    """Return an installer that swaps the LLM client for a scripted fake.

    Call ``install(plan1, plan2, ...)`` where each plan is a list of fake
    messages returned by one ``_run_chat_completion`` invocation. Returns the
    factory so the test can inspect ``factory.requests``.
    """

    def install(*plans):
        factory = _FakeOpenAIFactory(plans)
        monkeypatch.setattr("features.ai.services._new_llm_client", factory)
        return factory

    return install


def _raise(exc: Exception):
    def _boom(*_args, **_kwargs):
        raise exc

    return _boom


def _seed_long_conversation(session_factory):
    """A recipe conversation whose unsummarized history exceeds the trigger."""
    with session_factory() as session:
        session.add(
            AiConversation(
                id="conv-summary",
                subject_type="recipe",
                subject_id="recipe-1",
                prompt_version="v1",
                summary=None,
                summary_through_message_id=None,
                created_at=datetime(2026, 7, 23, 13, 0, 0),
                updated_at=datetime(2026, 7, 23, 13, 0, 0),
            )
        )
        for idx in range((_SUMMARY_TRIGGER_MESSAGES + 2) // 2):
            created = datetime(2026, 7, 23, 13, idx, 0)
            session.add(
                AiMessage(
                    conversation_id="conv-summary",
                    role="user",
                    content=f"Старый вопрос {idx}",
                    created_at=created,
                )
            )
            session.add(
                AiMessage(
                    conversation_id="conv-summary",
                    role="assistant",
                    content=f"Старый ответ {idx}",
                    created_at=created,
                )
            )
        session.commit()


# --------------------------------------------------------------------------- #
# Pure helpers                                                                 #
# --------------------------------------------------------------------------- #


def test_localized_default_question_translates():
    assert _localized_default_question("recipe", False, "ru-RU") == (
        "Проверь рецепт, всё ли с ним ок?"
    )
    assert _localized_default_question("recipe", False, "de-DE") == "Is this recipe okay?"


def test_sample_keeps_only_requested_fields():
    telemetry = _sample(
        [SimpleNamespace(timestamp="2026-07-22", gravity=1012.0, temperature=20.0, battery=92.0)],
        ("timestamp", "gravity", "temperature"),
    )
    assert telemetry == [{"timestamp": "2026-07-22", "gravity": 1012.0, "temperature": 20.0}]


# --------------------------------------------------------------------------- #
# Conversations                                                               #
# --------------------------------------------------------------------------- #


async def test_open_conversation_bootstraps_brew(db, install_llm):
    factory = install_llm([_message("Первичный ответ.")])
    conversation = await open_conversation("brew_session", "brew-1")

    assert conversation["messages"][0]["content"] == "Как идёт варка?"
    assert conversation["messages"][1]["content"] == "Первичный ответ."
    request = factory.requests[0]
    assert request["temperature"] == LLM_TEMPERATURE
    assert request["messages"][0]["role"] == "system"
    assert "<current_session_context>" in request["messages"][0]["content"]
    assert (
        request["messages"][-1]["content"].strip() == DEFAULT_INSTRUCTIONS[("brew", False)].strip()
    )
    assert "Reply using browser locale ru." in request["messages"][0]["content"]
    assert {tool["function"]["name"] for tool in request["tools"]} == {
        "list_brew_sessions",
        "list_fermentation_sessions",
        "search_sessions",
        "get_session_context",
    }


async def test_open_conversation_localizes_to_english(db, install_llm):
    factory = install_llm([_message("Fermentation is active.")])
    conversation = await open_conversation("fermentation_session", "ferm-1", "en-US")

    assert conversation["messages"][0]["content"] == "How is fermentation going?"
    assert "Reply using browser locale en-US." in factory.requests[0]["messages"][0]["content"]


async def test_reopen_returns_existing_without_calling_llm(db, install_llm):
    install_llm([_message("Первичный ответ.")])
    conversation = await open_conversation("brew_session", "brew-1")

    reopen_factory = install_llm()  # no plans queued: must not be invoked
    reopened = await open_conversation("brew_session", "brew-1")

    assert reopened["id"] == conversation["id"]
    assert len(reopened["messages"]) == 2
    assert reopen_factory.requests == []


async def test_followup_uses_history_and_persists(db, install_llm):
    install_llm([_message("Первичный ответ.")])
    conversation = await open_conversation("brew_session", "brew-1")

    factory = install_llm([_message("Краткий follow-up.")])
    turn = await send_conversation_message(conversation["id"], "  А температуру поднять?  ")

    assert turn["user_message"]["content"] == "А температуру поднять?"
    assert turn["assistant_message"]["content"] == "Краткий follow-up."
    request = factory.requests[0]
    assert request["temperature"] == LLM_CHAT_TEMPERATURE
    assert request["messages"][0]["role"] == "system"
    assert request["messages"][1]["content"] == "Как идёт варка?"
    assert request["messages"][2]["content"] == "Первичный ответ."
    assert request["messages"][-1] == {"role": "user", "content": "А температуру поднять?"}
    assert _count_messages(db.SessionLocal, conversation["id"]) == 4


async def test_send_uses_fresh_session_data(db, install_llm):
    install_llm([_message("Первичный ответ.")])
    conversation = await open_conversation("brew_session", "brew-1")

    with db.SessionLocal() as session:
        latest = session.scalar(
            sa.select(BrewTelemetry)
            .where(BrewTelemetry.session_id == "brew-1")
            .order_by(BrewTelemetry.timestamp.desc())
        )
        latest.temperature = 67.5
        latest.target_temperature = 68.0
        session.commit()

    factory = install_llm([_message("Использую свежие данные.")])
    await send_conversation_message(conversation["id"], "Что сейчас по температуре?")

    system = factory.requests[0]["messages"][0]["content"]
    assert '"temperature":67.5' in system
    assert '"target_temperature":68.0' in system


async def test_failed_llm_call_does_not_persist(db, install_llm, monkeypatch):
    install_llm([_message("Первичный ответ.")])
    conversation = await open_conversation("brew_session", "brew-1")

    monkeypatch.setattr("features.ai.services._run_chat_completion", _raise(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        await send_conversation_message(conversation["id"], "Этот ход должен упасть")

    assert _count_messages(db.SessionLocal, conversation["id"]) == 2


async def test_utf8_content_roundtrips(db, install_llm):
    install_llm([_message("Первичный ответ.")])
    conversation = await open_conversation("brew_session", "brew-1")

    install_llm([_message("Ответ по-русски: всё нормально.")])
    turn = await send_conversation_message(conversation["id"], "Русский вопрос: всё ок?")

    assert turn["user_message"]["content"] == "Русский вопрос: всё ок?"
    assert turn["assistant_message"]["content"] == "Ответ по-русски: всё нормально."


async def test_reset_conversation_clears_and_rebootstraps(db, install_llm):
    install_llm([_message("Первичный ответ.")])
    conversation = await open_conversation("brew_session", "brew-1")

    factory = install_llm([_message("Новая стартовая оценка.")])
    result = await reset_conversation(conversation["id"])

    assert result["id"] == conversation["id"]
    assert [message["content"] for message in result["messages"]] == [
        "Как идёт варка?",
        "Новая стартовая оценка.",
    ]
    assert _count_messages(db.SessionLocal, conversation["id"]) == 2
    assert factory.requests[0]["temperature"] == LLM_TEMPERATURE
    with db.SessionLocal() as session:
        row = session.get(AiConversation, conversation["id"])
        assert row.summary is None
        assert row.summary_through_message_id is None


async def test_summary_triggers_on_long_history(db, install_llm):
    _seed_long_conversation(db.SessionLocal)

    factory = install_llm([_message("Сжатое резюме.")], [_message("Ответ с summary.")])
    await send_conversation_message("conv-summary", "Новый вопрос после длинной истории")

    assert len(factory.requests) == 2
    assert factory.requests[0]["messages"][0]["content"]
    assert "Старый вопрос 0" in factory.requests[0]["messages"][1]["content"]
    main_system = factory.requests[1]["messages"][0]["content"]
    assert "[CONVERSATION SUMMARY]" in main_system
    assert "Сжатое резюме." in main_system
    assert len(factory.requests[1]["messages"]) == 1 + _RECENT_MESSAGES + 1
    with db.SessionLocal() as session:
        assert session.get(AiConversation, "conv-summary").summary == "Сжатое резюме."


async def test_summary_rolls_forward_incrementally(db, install_llm):
    _seed_long_conversation(db.SessionLocal)

    install_llm([_message("Сжатое резюме.")], [_message("Ответ с summary.")])
    await send_conversation_message("conv-summary", "Новый вопрос после длинной истории")

    with db.SessionLocal() as session:
        first_marker = session.get(AiConversation, "conv-summary").summary_through_message_id
        for idx in range(20, 34):
            created = datetime(2026, 7, 23, 14, idx - 20, 0)
            session.add(
                AiMessage(
                    conversation_id="conv-summary",
                    role="user",
                    content=f"Новый вопрос {idx}",
                    created_at=created,
                )
            )
            session.add(
                AiMessage(
                    conversation_id="conv-summary",
                    role="assistant",
                    content=f"Новый ответ {idx}",
                    created_at=created,
                )
            )
        session.commit()

    factory = install_llm([_message("Обновлённое резюме.")], [_message("Ещё один ответ.")])
    await send_conversation_message("conv-summary", "Ещё один новый вопрос")

    assert "Старый вопрос 0" not in factory.requests[0]["messages"][1]["content"]
    with db.SessionLocal() as session:
        assert session.get(AiConversation, "conv-summary").summary_through_message_id > first_marker


async def test_summary_failure_falls_back_to_recent(db, install_llm, monkeypatch):
    _seed_long_conversation(db.SessionLocal)

    monkeypatch.setattr(
        "features.ai.services._summarize_messages", _raise(RuntimeError("summary failed"))
    )
    factory = install_llm([_message("Ответ без summary.")])
    await send_conversation_message("conv-summary", "Проверь fallback summary")

    assert factory.requests[0]["messages"][-1]["content"] == "Проверь fallback summary"
    assert len(factory.requests[0]["messages"]) <= 1 + _SUMMARY_TRIGGER_MESSAGES + 1


# --------------------------------------------------------------------------- #
# Recipe wizard                                                               #
# --------------------------------------------------------------------------- #


async def test_generate_profile_happy_path(install_llm):
    factory = install_llm(
        [_recipe_spec_message()],
        [_message(_VALID_SEMANTIC_VALIDATION)],
    )
    stages: list[str] = []
    profile = await generate_profile(
        "Американский pale ale, 23 литра. Кип 60 минут, хмель за 15 минут до конца.",
        stages.append,
    )

    assert stages == ["generating", "checking_structure", "checking_recipe"]
    assert profile["public"] is False
    assert profile["profile_type_id"] is None
    assert profile["profile_type_name"] is None
    assert profile["description"] == "Одноступенчатое затирание и кип 60 минут"
    assert profile["alerts"] == []
    assert [step["order"] for step in profile["steps"]] == list(range(len(profile["steps"])))
    assert [step["name"] for step in profile["steps"]] == [
        "Mash In",
        "Мальтозная пауза",
        "Mash Out",
        "Sparge",
        "Boil",
        "Cooling",
    ]
    assert profile["steps"][4]["alerts"][0] == {
        "id": None,
        "alertText": "Добавить хмель — до конца кипа 15 минут",
        "trigger": "Duration",
        "operator": None,
        "temperature": None,
        "gravity": None,
        "length": 2700,
    }
    request = factory.requests[0]
    assert request["temperature"] == 0
    assert request["tool_choice"] == "required"
    assert len(request["tools"]) == 1
    tool = request["tools"][0]["function"]
    assert tool["name"] == "submit_recipe_spec"
    schema = tool["parameters"]
    assert schema["additionalProperties"] is False
    assert "steps" not in schema["properties"]
    assert "mash_rests" in schema["properties"]
    assert "boil_additions" in schema["properties"]
    assert "include_sparge" in schema["properties"]
    assert "include_mash_out" in schema["properties"]
    assert "pump_enabled" not in schema["properties"]
    assert "pump_utilisation_pct" not in schema["properties"]
    wizard_system = request["messages"][0]["content"]
    assert "submit_recipe_spec" in wizard_system
    assert "Do not return prose or construct low-level profile steps" in wizard_system
    semantic_request = factory.requests[1]
    assert semantic_request["response_format"]["json_schema"]["name"] == "recipe_wizard_validation"
    assert "<source_description>" in semantic_request["messages"][1]["content"]
    assert "<candidate_profile>" in semantic_request["messages"][1]["content"]
    assert "Yeast and other" in semantic_request["messages"][0]["content"]


async def test_recipe_wizard_stream_emits_progress(install_llm):
    install_llm(
        [_recipe_spec_message()],
        [_message(_VALID_SEMANTIC_VALIDATION)],
    )
    response = await recipe_wizard_stream_endpoint(RecipeWizardRequest(description="Кип 60 минут"))
    events = [json.loads(chunk) async for chunk in response.body_iterator]

    assert [event["stage"] for event in events[:-1]] == [
        "generating",
        "checking_structure",
        "checking_recipe",
    ]
    assert events[-1]["type"] == "result"


def _redundant_heat_transition(data):
    data["steps"].insert(
        3,
        {
            **data["steps"][2],
            "name": "Heat to 78",
            "endType": "Temperature",
            "durationType": "Temperature",
            "length": None,
            "alerts": [],
        },
    )


def _wrong_mash_out_power(data):
    data["steps"][0]["heatingUtilisation"] = 90
    data["steps"].insert(
        1,
        {
            **data["steps"][1],
            "name": "Heat to first rest",
            "endType": "Temperature",
            "durationType": "Temperature",
            "length": None,
            "heatingUtilisation": 90,
            "pidEnabled": False,
            "alerts": [],
        },
    )
    data["steps"][2].update(heatingUtilisation=50, pidEnabled=True)
    data["steps"][3].update(heatingUtilisation=90, pidEnabled=False)
    data["steps"][5]["heatingUtilisation"] = 90
    data["steps"][6]["heatingUtilisation"] = 0


_WIZARD_ERROR_CASES = [
    (
        lambda d: d["steps"][1].__setitem__("durationType", "Start"),
        "target duration timer must start at temperature",
    ),
    (
        lambda d: (
            d["steps"][0].update(heatingUtilisation=0.9),
            d["steps"][1].update(heatingUtilisation=0.5),
            d["steps"][2].update(heatingUtilisation=0.5),
            d["steps"][4].update(heatingUtilisation=0.9),
            d["steps"][5].update(heatingUtilisation=0),
        ),
        "heating utilisation appears to use a fractional percentage",
    ),
    (
        lambda d: d["steps"][2].__setitem__("endType", "Temperature"),
        "mash-out completion configuration is invalid",
    ),
    (
        lambda d: d["steps"][3].__setitem__("durationType", "Temperature"),
        "sparge completion configuration is invalid",
    ),
    (
        lambda d: d["steps"][4].__setitem__("endType", "Temperature"),
        "boil completion configuration is invalid",
    ),
    (
        lambda d: d["steps"][5].__setitem__("pidEnabled", True),
        "cooling configuration is invalid",
    ),
    (
        lambda d: d["steps"][5].__setitem__("durationType", "Start"),
        "target step durationType must not be Start",
    ),
    (_redundant_heat_transition, "redundant heat transition"),
    (_wrong_mash_out_power, "mash-out heating utilisation does not match rest power"),
    (
        lambda d: d["steps"][2].__setitem__("temperature", 76),
        "mash-out temperature must be 78",
    ),
    (
        lambda d: d["steps"][4]["alerts"][0].__setitem__("length", 3601),
        "alert 0 occurs after step end",
    ),
    (
        lambda d: d["steps"][0].__setitem__("alerts", []),
        "mash-in temperature alert is required",
    ),
    (
        lambda d: d["steps"][0]["alerts"][0].__setitem__("temperature", None),
        "alert 0 temperature must be a finite number",
    ),
    (
        lambda d: (
            d["steps"][0].update(temperature=65),
            d["steps"][0]["alerts"][0].update(temperature=65),
            d["steps"][1].update(temperature=45),
        ),
        "actual=65, first_rest=45, expected=47-49",
    ),
    (
        lambda d: d["steps"][0].update(
            controlType="Ramp", endType="Duration", durationType="Start", length=600
        ),
        "mash-in must wait for manual completion",
    ),
    (
        lambda d: d["steps"][0].update(endType="Temperature", durationType="Start"),
        "mash-in must wait for manual completion",
    ),
    (
        lambda d: (
            d["steps"][0].__setitem__("heatingUtilisation", 90),
            d["steps"][4].__setitem__("heatingUtilisation", 50),
        ),
        "heating utilisation does not match profile heat power: actual=50.0, expected=90",
    ),
]


_WIZARD_SPEC_ERROR_CASES = [
    (
        lambda d: d["boil_additions"][0].__setitem__("offset_seconds", 3700),
        "boil addition occurs outside the boil",
    ),
    (
        lambda d: (
            d.__setitem__("mash_in_temperature_c", None),
            d.__setitem__("mash_rests", []),
        ),
        "mash-in temperature or at least one mash rest is required",
    ),
]


@pytest.mark.parametrize("mutator, expected", _WIZARD_SPEC_ERROR_CASES)
def test_compile_recipe_rejects_invalid_semantic_spec(mutator, expected):
    data = json.loads(json.dumps(_VALID_RECIPE_SPEC))
    mutator(data)
    with pytest.raises(ValueError) as error:
        compile_recipe(RecipeSpec.model_validate(data))
    assert expected in str(error.value)


def test_compile_recipe_preserves_explicit_low_mash_in():
    data = {
        **_VALID_RECIPE_SPEC,
        "mash_in_temperature_c": 38,
        "mash_in_alert_text": "Добавить солод",
        "mash_rests": [
            {
                "temperature_c": 45,
                "duration_seconds": 900,
            }
        ],
    }

    profile = compile_recipe(RecipeSpec.model_validate(data))

    assert [step["name"] for step in profile["steps"][:2]] == [
        "Mash In",
        "45 °C",
    ]
    assert profile["steps"][0]["temperature"] == 38
    assert profile["steps"][0]["endType"] == "Manual"


async def test_generate_profile_repairs_structural_error(install_llm):
    factory = install_llm(
        [_recipe_spec_message({"name": "bad"})],
        [_recipe_spec_message()],
        [_message(_VALID_SEMANTIC_VALIDATION)],
    )
    profile = await generate_profile("Собери профиль IPA с кипом 60 минут")

    assert profile["steps"][0]["order"] == 0
    assert len(factory.requests) == 3
    retry_messages = factory.requests[1]["messages"]
    for token in (
        "submit_recipe_spec again",
        "previous attempt failed",
        "Field required",
    ):
        assert token in retry_messages[-1]["content"]


async def test_generate_profile_repairs_semantic_error(install_llm):
    factory = install_llm(
        [_recipe_spec_message()],
        [
            _message(
                '{"valid":false,"errors":["Boil spice alert length: expected 3000, actual 600."]}'
            )
        ],
        [_recipe_spec_message()],
        [_message(_VALID_SEMANTIC_VALIDATION)],
    )
    stages: list[str] = []
    profile = await generate_profile(
        "Кип 60 минут. Специи за 10 минут до конца кипа.",
        stages.append,
    )

    assert stages == [
        "generating",
        "checking_structure",
        "checking_recipe",
        "repairing",
        "checking_fixed_structure",
        "checking_fixed_recipe",
    ]
    assert profile["steps"][4]["length"] == 3600
    retry_message = factory.requests[2]["messages"][-1]["content"]
    assert "Recipe mismatches:" in retry_message
    assert "expected 3000, actual 600" in retry_message


def test_compile_recipe_applies_power_and_pid_rules():
    data = json.loads(json.dumps(_VALID_RECIPE_SPEC))
    data.update(heat_power_pct=90, rest_power_pct=50, mash_pid_enabled=True)

    profile = compile_recipe(RecipeSpec.model_validate(data))

    mash_in = profile["steps"][0]
    first_rest = profile["steps"][1]
    mash_out = next(step for step in profile["steps"] if step["name"] == "Mash Out")
    mash_out_transition = profile["steps"][profile["steps"].index(mash_out) - 1]
    boil = next(step for step in profile["steps"] if step["name"] == "Boil")
    assert mash_in["heatingUtilisation"] == 90
    assert first_rest["heatingUtilisation"] == 50
    assert first_rest["pidEnabled"] is True
    assert mash_out_transition["endType"] == "Temperature"
    assert mash_out_transition["heatingUtilisation"] == 90
    assert boil["heatingUtilisation"] == 90
    assert boil["pidEnabled"] is False


def test_compile_recipe_applies_defaults_and_boil_timing():
    data = json.loads(json.dumps(_VALID_RECIPE_SPEC))
    data["mash_in_temperature_c"] = None
    data["mash_out_end_alert_text"] = "Mash Out завершён"
    data["boil_additions"].append(
        {
            "text": "Добавить сахар через 10 минут",
            "timing_reference": "from_start",
            "offset_seconds": 600,
        }
    )

    profile = compile_recipe(RecipeSpec.model_validate(data))

    assert profile["steps"][0]["temperature"] == 70
    boil = next(step for step in profile["steps"] if step["name"] == "Boil")
    assert [alert["length"] for alert in boil["alerts"]] == [2700, 600]
    mash_out = next(step for step in profile["steps"] if step["name"] == "Mash Out")
    assert mash_out["temperature"] == 78
    assert mash_out["alerts"][0]["trigger"] == "StepEnd"
    assert profile["steps"][-1]["temperature"] == 20


def test_compile_recipe_preserves_blanche_alerts_and_final_mash_out():
    data = {
        **_VALID_RECIPE_SPEC,
        "mash_in_temperature_c": 48,
        "mash_rests": [
            {
                "name": f"Пауза {temperature} °C",
                "temperature_c": temperature,
                "duration_seconds": duration * 60,
                "end_alert_text": f"Пауза {temperature} °C завершена",
            }
            for temperature, duration in [(45, 15), (50, 10), (63, 30), (65, 20), (72, 20), (78, 5)]
        ],
        "heat_power_pct": 90,
        "rest_power_pct": 50,
        "mash_pid_enabled": True,
        "mash_out_duration_seconds": 600,
        "mash_out_end_alert_text": "Mash Out завершён",
        "sparge_alert_text": "Начать промывку",
    }

    profile = compile_recipe(RecipeSpec.model_validate(data))

    assert profile["steps"][1]["name"] == "Пауза 45 °C"
    assert profile["steps"][1]["heatingUtilisation"] == 50
    assert [step["name"] for step in profile["steps"]].count("Mash Out") == 1
    mash_out = next(step for step in profile["steps"] if step["name"] == "Mash Out")
    assert mash_out["length"] == 300
    assert mash_out["alerts"][0] == {
        "id": None,
        "alertText": "Пауза 78 °C завершена",
        "trigger": "StepEnd",
        "operator": None,
        "temperature": None,
        "gravity": None,
        "length": None,
    }
    rests = [
        step
        for step in profile["steps"]
        if step["name"].startswith("Пауза") or step["name"] == "Mash Out"
    ]
    assert all(any(alert["trigger"] == "StepEnd" for alert in step["alerts"]) for step in rests)
    sparge = next(step for step in profile["steps"] if step["name"] == "Sparge")
    assert sparge["alerts"][0]["trigger"] == "StepStart"
    assert sparge["heatingUtilisation"] == 0
    assert sparge["pidEnabled"] is False
    assert all(
        step["pumpEnabled"] is None and step["pumpUtilisation"] is None for step in profile["steps"]
    )


def test_compile_recipe_honors_disabled_setup_features():
    data = {
        **_VALID_RECIPE_SPEC,
        "mash_in_alert_text": None,
        "include_temperature_alerts": False,
        "include_sparge": False,
        "include_mash_out": False,
    }

    profile = compile_recipe(RecipeSpec.model_validate(data))

    names = [step["name"] for step in profile["steps"]]
    assert "Mash Out" not in names
    assert "Sparge" not in names
    assert all(
        alert["trigger"] != "Temperature" for step in profile["steps"] for alert in step["alerts"]
    )


async def test_generate_profile_gives_up_after_second_failure(install_llm):
    install_llm([_message('{"name":"bad"}')], [_message("[]")])
    with pytest.raises(ValueError, match="Модель не смогла собрать корректный профиль"):
        await generate_profile("Собери профиль стаута")


async def test_generate_profile_rejects_forbidden_enums(install_llm):
    freerise_step = {
        "id": None,
        "name": "Mash step",
        "order": 0,
        "controlType": "FreeRise",
        "endType": "Duration",
        "durationType": "Start",
        "operator": None,
        "length": 600,
        "temperature": None,
        "minTemperature": None,
        "maxTemperature": None,
        "gravity": None,
        "pumpEnabled": None,
        "pumpUtilisation": None,
        "heatingUtilisation": None,
        "pidEnabled": None,
        "sensorDifferential": None,
        "alerts": [],
    }
    gravity_alert_step = {
        "id": None,
        "name": "Mash step",
        "order": 0,
        "controlType": "Target",
        "endType": "Duration",
        "durationType": "Temperature",
        "operator": None,
        "length": 600,
        "temperature": 66,
        "minTemperature": None,
        "maxTemperature": None,
        "gravity": None,
        "pumpEnabled": None,
        "pumpUtilisation": None,
        "heatingUtilisation": None,
        "pidEnabled": None,
        "sensorDifferential": None,
        "alerts": [
            {
                "id": None,
                "alertText": "Gravity alert",
                "trigger": "Gravity",
                "operator": None,
                "temperature": None,
                "gravity": 1.01,
                "length": None,
            }
        ],
    }

    def _profile(step):
        return json.dumps(
            {
                "name": "Bad recipe",
                "description": None,
                "public": False,
                "profile_type_id": None,
                "profile_type_name": None,
                "steps": [step],
                "alerts": [],
            }
        )

    invalid_spec = {**_VALID_RECIPE_SPEC, "steps": [freerise_step, gravity_alert_step]}
    install_llm(
        [_recipe_spec_message(invalid_spec)],
        [_recipe_spec_message(invalid_spec)],
    )
    with pytest.raises(ValueError, match="Модель не смогла собрать корректный профиль"):
        await generate_profile("Собери профиль с неверными enum")


async def test_generate_profile_repairs_missing_alert_text(install_llm):
    invalid_spec = {**_VALID_RECIPE_SPEC, "mash_in_alert_text": ""}
    factory = install_llm(
        [_recipe_spec_message(invalid_spec)],
        [_recipe_spec_message()],
        [_message(_VALID_SEMANTIC_VALIDATION)],
    )
    profile = await generate_profile("Рецепт с хмелем и охлаждением после кипа.")

    assert profile["steps"][4]["alerts"][0]["alertText"]
    retry_message = factory.requests[1]["messages"][-1]["content"]
    assert "String should have at least 1 character" in retry_message
