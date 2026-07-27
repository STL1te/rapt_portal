"""Offline checks for the OpenAI-compatible AI workflow."""

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import sqlalchemy as sa
from openai import BadRequestError
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import ASSISTANT_LLM, LLM_CHAT_TEMPERATURE, LLM_TEMPERATURE
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
from features.ai.beerjson_schema import assert_valid_beerjson
from features.ai.brewzilla_overrides import BrewZillaOverrides
from features.ai.recipe_wizard import (
    RECIPE_WIZARD_VALIDATOR_PROMPT,
    WIZARD_LLM,
    SubmitRecipe,
    _parse_semantic_validation,
    _response_format_fallbacks,
    _run_semantic_validator,
    generate_profile,
)
from features.ai.router import RecipeWizardRequest, recipe_wizard_stream_endpoint
from features.ai.services import (
    _RECENT_MESSAGES,
    _SUMMARY_TRIGGER_MESSAGES,
    DEFAULT_INSTRUCTIONS,
    _localized_default_question,
    _new_llm_client,
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

    def __call__(self, *_args, **_kwargs):
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


_VALID_SEMANTIC_VALIDATION = '{"valid":true,"errors":[]}'
_VALID_SUBMIT_RECIPE = {
    "recipe": {
        "name": "APA 23 л",
        "type": "all grain",
        "notes": "Одноступенчатое затирание и кип 60 минут",
        "ingredients": {
            "fermentable_additions": [
                {"name": "Pale Ale malt", "type": "grain", "amount": {"unit": "kg", "value": 5}}
            ],
            "hop_additions": [
                {
                    "name": "Cascade",
                    "amount": {"unit": "g", "value": 20},
                    "timing": {"use": "add_to_boil", "duration": {"unit": "min", "value": 15}},
                }
            ],
            "culture_additions": [{"name": "US-05", "amount": {"unit": "pkg", "value": 1}}],
        },
        "mash": {
            "mash_steps": [
                {
                    "name": "Мальтозная пауза",
                    "type": "temperature",
                    "step_temperature": {"unit": "C", "value": 67},
                    "step_time": {"unit": "min", "value": 60},
                }
            ]
        },
        "boil": {"boil_time": {"unit": "min", "value": 60}},
    },
    "brewzilla_overrides": {
        "mash_in_temperature_c": 69,
        "mash_in_alert_text": "Засыпать солод",
    },
}


def _recipe_message(submit=None):
    return _message(json.dumps(submit or _VALID_SUBMIT_RECIPE, ensure_ascii=False))


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
        # pin sampling so the assertions below don't depend on the dev's .env
        monkeypatch.setattr(ASSISTANT_LLM, "sampling", "default")
        return factory

    return install


def _raise(exc: Exception):
    def _boom(*_args, **_kwargs):
        raise exc

    return _boom


def test_llm_client_retries_transient_failures(monkeypatch):
    captured: dict = {}

    def create_client(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr("features.ai.services.AsyncOpenAI", create_client)

    _new_llm_client(ASSISTANT_LLM)

    assert captured["max_retries"] == 2
    assert captured["base_url"] == ASSISTANT_LLM.base_url


def test_semantic_validator_accepts_fenced_json():
    assert _parse_semantic_validation('```json\n{"valid":true,"errors":[]}\n```') == []


def test_semantic_validator_honors_configured_response_format(monkeypatch):
    monkeypatch.setattr(WIZARD_LLM, "response_format", "json_object")

    schema_format = {"type": "json_schema", "json_schema": {"name": "x"}}
    assert _response_format_fallbacks(schema_format) == (("JSON mode", {"type": "json_object"}),)


async def test_semantic_validator_falls_back_through_json_formats(monkeypatch, caplog):
    requests: list[dict] = []
    monkeypatch.setattr(WIZARD_LLM, "response_format", "auto")

    async def complete(_messages, **kwargs):
        requests.append(kwargs)
        if len(requests) < 3:
            raise BadRequestError(
                "response_format is unavailable",
                response=httpx.Response(
                    400,
                    request=httpx.Request("POST", "https://llm.example.test/v1/chat/completions"),
                ),
                body=None,
            )
        return '{"valid":true,"errors":[]}'

    monkeypatch.setattr("features.ai.recipe_wizard._run_chat_completion", complete)
    submit = SubmitRecipe.model_validate(_VALID_SUBMIT_RECIPE)

    result = await _run_semantic_validator("Recipe description", submit)

    assert _parse_semantic_validation(result) == []
    assert requests[0]["response_format"]["type"] == "json_schema"
    assert requests[1]["response_format"] == {"type": "json_object"}
    assert "response_format" not in requests[2]
    assert "LLM response format is incompatible" in caplog.text


def _seed_long_conversation(session_factory):
    """A recipe conversation whose unsummarized history exceeds the trigger."""
    with session_factory() as session:
        session.add(
            AiConversation(
                id="conv-summary",
                subject_type="profile",
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
    assert _localized_default_question("profile", False, "ru-RU") == (
        "Проверь профиль, всё ли с ним ок?"
    )
    assert _localized_default_question("profile", False, "de-DE") == "Is this profile okay?"


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


async def test_generate_profile_happy_path(install_llm, monkeypatch):
    monkeypatch.setattr(WIZARD_LLM, "response_format", "auto")
    factory = install_llm(
        [_recipe_message()],
        [_message(_VALID_SEMANTIC_VALIDATION)],
    )
    stages: list[str] = []
    profile, recipe = await generate_profile(
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
    boil_alert = profile["steps"][4]["alerts"][0]
    assert boil_alert["alertText"] == "20 g Cascade"
    assert boil_alert["trigger"] == "Duration"
    assert boil_alert["length"] == 2700
    assert_valid_beerjson(recipe)
    assert recipe["beerjson"]["recipes"][0]["name"] == "APA 23 л"
    request = factory.requests[0]
    assert request["temperature"] == 0
    assert "tools" not in request
    assert request["max_tokens"] == 16_384
    response_format = request["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "submit_recipe"
    assert response_format["json_schema"]["strict"] is True
    schema = response_format["json_schema"]["schema"]
    assert "minLength" not in json.dumps(schema) and "maxLength" not in json.dumps(schema)
    assert schema["required"] == ["recipe", "brewzilla_overrides"]
    recipe_def = schema["$defs"]["RecipeModel"]
    assert recipe_def["required"] == list(recipe_def["properties"])
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {"recipe", "brewzilla_overrides"}
    defs = schema["$defs"]
    assert "mash_additions" in defs["BrewZillaOverrides"]["properties"]
    assert "boil" in defs["RecipeModel"]["properties"]
    assert "ingredients" in defs["RecipeModel"]["properties"]
    assert "mash_out_temperature_c" in defs["BrewZillaOverrides"]["properties"]
    assert "sparge_temperature_c" in defs["BrewZillaOverrides"]["properties"]
    assert "include_sparge" in defs["BrewZillaOverrides"]["properties"]
    assert "include_mash_out" in defs["BrewZillaOverrides"]["properties"]
    wizard_system = request["messages"][0]["content"]
    assert "submit_recipe" in wizard_system
    assert "Do not return prose" in wizard_system
    assert "JSON schema is authoritative" in wizard_system
    assert "Never submit partial objects" in wizard_system
    assert "add_to_boil" in wizard_system
    validator_system = RECIPE_WIZARD_VALIDATOR_PROMPT
    assert "already passed schema validation" in validator_system
    assert "Do not reason" in validator_system
    assert "exporter step ordering" in validator_system
    semantic_request = factory.requests[1]
    assert semantic_request["response_format"]["type"] == "json_schema"
    assert semantic_request["max_tokens"] == 16_384
    semantic_content = semantic_request["messages"][1]["content"]
    assert "<source_description>" in semantic_content
    assert "<candidate_spec>" in semantic_content
    spec_json = semantic_content.split("<candidate_spec>", 1)[1].split("</candidate_spec>", 1)[0]
    candidate = json.loads(spec_json)
    assert [
        addition["name"] for addition in candidate["recipe"]["ingredients"]["hop_additions"]
    ] == [
        addition["name"]
        for addition in _VALID_SUBMIT_RECIPE["recipe"]["ingredients"]["hop_additions"]
    ]
    assert candidate["brewzilla_overrides"]["mash_in_temperature_c"] == 69
    assert "ingredient names copied character for character" in validator_system


async def test_semantic_validator_uses_dedicated_judge_model(install_llm, monkeypatch):
    monkeypatch.setattr(WIZARD_LLM, "validator_model", "judge-model")
    factory = install_llm(
        [_recipe_message()],
        [_message(_VALID_SEMANTIC_VALIDATION)],
    )

    await generate_profile("Кип 60 минут")

    assert factory.requests[0]["model"] != "judge-model"
    assert factory.requests[1]["model"] == "judge-model"


async def test_generate_profile_applies_user_overrides_over_extracted(install_llm):
    install_llm(
        [_recipe_message()],
        [_message(_VALID_SEMANTIC_VALIDATION)],
    )

    profile, _recipe = await generate_profile(
        "Американский pale ale, 23 литра. Кип 60 минут, хмель за 15 минут до конца.",
        user_overrides=BrewZillaOverrides(mash_in_temperature_c=66),
    )

    assert profile["steps"][0]["temperature"] == 66


async def test_generate_profile_retries_broken_semantic_validator_without_repair(install_llm):
    factory = install_llm(
        [_recipe_message()],
        [_message("not json " * 1000)],
        [_message(_VALID_SEMANTIC_VALIDATION)],
    )
    stages: list[str] = []
    profile, _recipe = await generate_profile("Кип 60 минут", stages.append)

    assert profile["steps"][-1]["name"] == "Cooling"
    assert stages == ["generating", "checking_structure", "checking_recipe"]
    assert len(factory.requests) == 3
    assert factory.requests[1]["max_tokens"] == 16_384
    assert factory.requests[2]["max_tokens"] == 16_384


async def test_generate_profile_logs_broken_semantic_validator_reason(install_llm, caplog):
    install_llm(
        [_recipe_message()],
        [_message("not json " * 1000)],
        [_message('{"valid":true,"errors":["contradiction"]}')],
        [_recipe_message()],
        [_message("[]")],
        [_message('{"valid":true,"errors":["still bad"]}')],
    )

    with pytest.raises(ValueError) as error:
        await generate_profile("Кип 60 минут")

    assert str(error.value) == "Модель не смогла собрать корректный профиль"
    cause = error.value.__cause__
    assert cause is not None
    assert "invalid result twice" in str(cause)
    assert "invalid shape" in str(cause)
    assert "still bad" in str(cause)
    assert "not json" in caplog.text
    assert "non-object JSON" in caplog.text
    assert "contradiction" in caplog.text


async def test_recipe_wizard_stream_emits_progress(install_llm):
    install_llm(
        [_recipe_message()],
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
    assert_valid_beerjson(events[-1]["recipe"])


async def test_generate_profile_repairs_structural_error(install_llm):
    factory = install_llm(
        # partial recipes are valid now, so plant a genuinely broken step instead
        [_recipe_message({"recipe": {"mash": {"mash_steps": [{"type": "infusion"}]}}})],
        [_recipe_message()],
        [_message(_VALID_SEMANTIC_VALIDATION)],
    )
    profile, _recipe = await generate_profile("Собери профиль IPA с кипом 60 минут")

    assert profile["steps"][0]["order"] == 0
    assert len(factory.requests) == 3
    retry_messages = factory.requests[1]["messages"]
    for token in (
        "submit_recipe again",
        "previous attempt failed",
        "Field required",
    ):
        assert token in retry_messages[-1]["content"]


async def test_generate_profile_repairs_semantic_error(install_llm):
    factory = install_llm(
        [_recipe_message()],
        [
            _message(
                '{"valid":false,"errors":["Boil spice alert length: expected 3000, actual 600."]}'
            )
        ],
        [_recipe_message()],
        [_message(_VALID_SEMANTIC_VALIDATION)],
    )
    stages: list[str] = []
    profile, _recipe = await generate_profile(
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


async def test_generate_profile_returns_best_effort_after_second_semantic_mismatch(
    install_llm, caplog
):
    """Second attempt still fails semantic validation, but extraction/compile succeeded:
    hand back the imperfect profile instead of a dead end (unlike a structural failure,
    which has no profile to salvage)."""
    install_llm(
        [_recipe_message()],
        [
            _message(
                '{"valid":false,"errors":["Boil spice alert length: expected 3000, actual 600."]}'
            )
        ],
        [_recipe_message()],
        [_message('{"valid":false,"errors":["still off by one field"]}')],
    )
    profile, _recipe = await generate_profile("Кип 60 минут. Специи за 10 минут до конца кипа.")

    assert profile["steps"][4]["length"] == 3600
    assert "still off by one field" in caplog.text


async def test_generate_profile_gives_up_after_second_failure(install_llm):
    install_llm([_message('{"name":"bad"}')], [_message("[]")])
    with pytest.raises(ValueError, match="Модель не смогла собрать корректный профиль"):
        await generate_profile("Собери профиль стаута")


async def test_generate_profile_rejects_unknown_tool_fields(install_llm):
    invalid_submit = {**_VALID_SUBMIT_RECIPE, "unexpected_field": True}
    install_llm(
        [_recipe_message(invalid_submit)],
        [_recipe_message(invalid_submit)],
    )
    with pytest.raises(ValueError, match="Модель не смогла собрать корректный профиль"):
        await generate_profile("Собери профиль с лишним полем")


async def test_generate_profile_repairs_missing_alert_text(install_llm):
    invalid_submit = {
        **_VALID_SUBMIT_RECIPE,
        "brewzilla_overrides": {
            **_VALID_SUBMIT_RECIPE["brewzilla_overrides"],
            "mash_in_alert_text": "",
        },
    }
    factory = install_llm(
        [_recipe_message(invalid_submit)],
        [_recipe_message()],
        [_message(_VALID_SEMANTIC_VALIDATION)],
    )
    profile, _recipe = await generate_profile("Рецепт с хмелем и охлаждением после кипа.")

    assert profile["steps"][4]["alerts"][0]["alertText"]
    retry_message = factory.requests[1]["messages"][-1]["content"]
    assert "String should have at least 1 character" in retry_message


def test_recipe_wizard_accepts_detailed_human_recipe():
    request = RecipeWizardRequest(description="Рецепт: " + "а" * 7_500)

    assert len(request.description) > 4_000
