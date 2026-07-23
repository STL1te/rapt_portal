"""Offline checks for the OpenAI-compatible AI workflow."""

import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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
from features.ai.services import (
    _RECENT_MESSAGES,
    _SUMMARY_TRIGGER_MESSAGES,
    DEFAULT_INSTRUCTIONS,
    _sample,
    _validate_generated_profile,
    assess,
    generate_profile,
    open_conversation,
    reset_conversation,
    review_recipe,
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


def _tool_call(name: str, arguments: str, call_id: str = "call-1"):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


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
                "durationType": "Start",
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
                "durationType": "Start",
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


async def main() -> None:
    telemetry = _sample(
        [SimpleNamespace(timestamp="2026-07-22", gravity=1012.0, temperature=20.0, battery=92.0)],
        ("timestamp", "gravity", "temperature"),
    )
    assert telemetry == [{"timestamp": "2026-07-22", "gravity": 1012.0, "temperature": 20.0}]

    db = _TestDb()
    _seed_db(db.SessionLocal)
    try:
        bootstrap_factory = _FakeOpenAIFactory([[_message("Первичный ответ.")]])
        with (
            patch("features.ai.services.SessionLocal", db.SessionLocal),
            patch("features.ai.services.AsyncOpenAI", bootstrap_factory),
        ):
            conversation = await open_conversation("brew_session", "brew-1")

        assert conversation["messages"][0]["content"] == "Как идёт варка?"
        assert conversation["messages"][1]["content"] == "Первичный ответ."
        assert bootstrap_factory.requests[0]["temperature"] == LLM_TEMPERATURE
        assert bootstrap_factory.requests[0]["messages"][0]["role"] == "system"
        assert (
            "<current_session_context>" in bootstrap_factory.requests[0]["messages"][0]["content"]
        )
        assert (
            bootstrap_factory.requests[0]["messages"][-1]["content"].strip()
            == DEFAULT_INSTRUCTIONS[("brew", False)].strip()
        )
        assert {tool["function"]["name"] for tool in bootstrap_factory.requests[0]["tools"]} == {
            "list_brew_sessions",
            "list_fermentation_sessions",
            "search_sessions",
            "get_session_context",
        }

        reopen_factory = _FakeOpenAIFactory([])
        with (
            patch("features.ai.services.SessionLocal", db.SessionLocal),
            patch("features.ai.services.AsyncOpenAI", reopen_factory),
        ):
            reopened = await open_conversation("brew_session", "brew-1")
        assert reopened["id"] == conversation["id"]
        assert len(reopened["messages"]) == 2
        assert reopen_factory.requests == []

        followup_factory = _FakeOpenAIFactory([[_message("Краткий follow-up.")]])
        with (
            patch("features.ai.services.SessionLocal", db.SessionLocal),
            patch("features.ai.services.AsyncOpenAI", followup_factory),
        ):
            turn = await send_conversation_message(conversation["id"], "  А температуру поднять?  ")
        assert turn["user_message"]["content"] == "А температуру поднять?"
        assert turn["assistant_message"]["content"] == "Краткий follow-up."
        assert followup_factory.requests[0]["temperature"] == LLM_CHAT_TEMPERATURE
        assert followup_factory.requests[0]["messages"][0]["role"] == "system"
        assert followup_factory.requests[0]["messages"][1]["content"] == "Как идёт варка?"
        assert followup_factory.requests[0]["messages"][2]["content"] == "Первичный ответ."
        assert followup_factory.requests[0]["messages"][-1] == {
            "role": "user",
            "content": "А температуру поднять?",
        }
        assert _count_messages(db.SessionLocal, conversation["id"]) == 4

        tool_factory = _FakeOpenAIFactory(
            [
                [
                    _message(
                        tool_calls=[
                            _tool_call(
                                "search_sessions",
                                '{"query":"tropicana","kind":"brew"}',
                            )
                        ]
                    ),
                    _message("Compared."),
                ]
            ]
        )
        with (
            patch("features.ai.services.AsyncOpenAI", tool_factory),
            patch("features.ai.services._run_tool", return_value={"sessions": []}) as run_tool,
        ):
            answer = await assess("brew", "current", "{}", "Compare with tropicana")
        assert answer == "Compared."
        assert len(tool_factory.requests) == 2
        run_tool.assert_called_once_with(
            "current", "search_sessions", {"query": "tropicana", "kind": "brew"}
        )
        assert tool_factory.requests[1]["messages"][-1]["role"] == "tool"

        recipe_factory = _FakeOpenAIFactory([[_message("Рецепт выглядит разумно.")]])
        with patch("features.ai.services.AsyncOpenAI", recipe_factory):
            recipe_answer = await review_recipe('{"name":"Русский стаут"}', None)
        assert recipe_answer == "Рецепт выглядит разумно."
        assert "tools" not in recipe_factory.requests[0]
        assert "<recipe_context>" in recipe_factory.requests[0]["messages"][0]["content"]

        with db.SessionLocal() as session:
            latest = session.scalar(
                sa.select(BrewTelemetry)
                .where(BrewTelemetry.session_id == "brew-1")
                .order_by(BrewTelemetry.timestamp.desc())
            )
            latest.temperature = 67.5
            latest.target_temperature = 68.0
            session.commit()

        fresh_factory = _FakeOpenAIFactory([[_message("Использую свежие данные.")]])
        with (
            patch("features.ai.services.SessionLocal", db.SessionLocal),
            patch("features.ai.services.AsyncOpenAI", fresh_factory),
        ):
            await send_conversation_message(conversation["id"], "Что сейчас по температуре?")
        fresh_system = fresh_factory.requests[0]["messages"][0]["content"]
        assert '"temperature":67.5' in fresh_system
        assert '"target_temperature":68.0' in fresh_system

        with patch("features.ai.services._run_chat_completion", side_effect=RuntimeError("boom")):
            try:
                with patch("features.ai.services.SessionLocal", db.SessionLocal):
                    await send_conversation_message(conversation["id"], "Этот ход должен упасть")
            except RuntimeError:
                pass
            else:
                raise AssertionError("Expected RuntimeError from failed LLM call")
        assert _count_messages(db.SessionLocal, conversation["id"]) == 6

        utf_factory = _FakeOpenAIFactory([[_message("Ответ по-русски: всё нормально.")]])
        with (
            patch("features.ai.services.SessionLocal", db.SessionLocal),
            patch("features.ai.services.AsyncOpenAI", utf_factory),
        ):
            utf_turn = await send_conversation_message(
                conversation["id"], "Русский вопрос: всё ок?"
            )
        assert utf_turn["user_message"]["content"] == "Русский вопрос: всё ок?"
        assert utf_turn["assistant_message"]["content"] == "Ответ по-русски: всё нормально."

        wizard_factory = _FakeOpenAIFactory([[_message(_VALID_WIZARD_JSON)]])
        with patch("features.ai.services.AsyncOpenAI", wizard_factory):
            profile = await generate_profile(
                "Американский pale ale, 23 литра. Кип 60 минут, хмель за 15 минут до конца."
            )
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
        wizard_request = wizard_factory.requests[0]
        response_format = wizard_request["response_format"]
        assert response_format["type"] == "json_schema"
        assert response_format["json_schema"]["strict"] is True
        schema = response_format["json_schema"]["schema"]
        assert schema["additionalProperties"] is False
        assert schema["properties"]["steps"]["minItems"] == 1
        step_schema = schema["properties"]["steps"]["items"]
        assert step_schema["additionalProperties"] is False
        assert step_schema["properties"]["controlType"]["enum"] == ["Target", "Ramp"]
        assert step_schema["properties"]["durationType"]["enum"] == [
            "Start",
            "Temperature",
            "Manual",
        ]
        assert step_schema["properties"]["alerts"]["items"]["additionalProperties"] is False
        wizard_system = wizard_request["messages"][0]["content"]
        for token in ("Target", "Ramp", "Duration", "StepStart", "GreaterThan"):
            assert token in wizard_system

        def assert_wizard_error(mutator, expected: str) -> None:
            invalid = json.loads(_VALID_WIZARD_JSON)
            mutator(invalid)
            try:
                _validate_generated_profile(json.dumps(invalid))
            except ValueError as error:
                assert expected in str(error)
            else:
                raise AssertionError(f"Expected wizard validation error: {expected}")

        assert_wizard_error(
            lambda data: data["steps"][1].__setitem__("durationType", "Start"),
            "target duration timer must start at temperature",
        )
        assert_wizard_error(
            lambda data: data["steps"][2].__setitem__("temperature", 76),
            "mash-out temperature must be 78",
        )
        assert_wizard_error(
            lambda data: data["steps"][4]["alerts"][0].__setitem__("length", 3601),
            "alert 0 occurs after step end",
        )
        assert_wizard_error(
            lambda data: data["steps"][0].__setitem__("alerts", []),
            "mash-in temperature alert is required",
        )
        assert_wizard_error(
            lambda data: data["steps"][0]["alerts"][0].__setitem__("temperature", None),
            "alert 0 temperature must be a finite number",
        )
        assert_wizard_error(
            lambda data: (
                data["steps"][0].update(temperature=65),
                data["steps"][0]["alerts"][0].update(temperature=65),
                data["steps"][1].update(temperature=45),
            ),
            "actual=65, first_rest=45, expected=47-49",
        )
        assert_wizard_error(
            lambda data: data["steps"][0].update(
                controlType="Ramp",
                endType="Duration",
                durationType="Start",
                length=600,
            ),
            "mash-in must wait for manual completion",
        )
        assert_wizard_error(
            lambda data: data["steps"][0].update(
                endType="Temperature",
                durationType="Start",
            ),
            "mash-in must wait for manual completion",
        )

        invalid_power = json.loads(_VALID_WIZARD_JSON)
        invalid_power["steps"][0]["heatingUtilisation"] = 90
        invalid_power["steps"][4]["heatingUtilisation"] = 50
        try:
            _validate_generated_profile(json.dumps(invalid_power))
        except ValueError as error:
            assert (
                "heating utilisation does not match profile heat power: actual=50.0, expected=90"
            ) in str(error)
        else:
            raise AssertionError("Expected invalid boil heating utilisation")

        retry_factory = _FakeOpenAIFactory(
            [[_message('{"name":"bad"}')], [_message(_VALID_WIZARD_JSON)]]
        )
        with patch("features.ai.services.AsyncOpenAI", retry_factory):
            retried_profile = await generate_profile("Собери профиль IPA с кипом 60 минут")
        assert retried_profile["steps"][0]["order"] == 0
        assert len(retry_factory.requests) == 2
        retry_messages = retry_factory.requests[1]["messages"]
        assert retry_messages[-2] == {"role": "assistant", "content": '{"name":"bad"}'}
        assert "Ошибка валидации" in retry_messages[-1]["content"]
        assert "Исправление:" in retry_messages[-1]["content"]
        assert "fixed profile fields are invalid" in retry_messages[-1]["content"]
        assert "public=false" in retry_messages[-1]["content"]

        failed_retry_factory = _FakeOpenAIFactory([[_message('{"name":"bad"}')], [_message("[]")]])
        with patch("features.ai.services.AsyncOpenAI", failed_retry_factory):
            try:
                await generate_profile("Собери профиль стаута")
            except ValueError as error:
                assert str(error) == "Модель не смогла собрать корректный профиль"
            else:
                raise AssertionError("Expected safe ValueError for invalid wizard retries")

        forbidden_enum_factory = _FakeOpenAIFactory(
            [
                [
                    _message(
                        json.dumps(
                            {
                                "name": "Bad recipe",
                                "description": None,
                                "public": False,
                                "profile_type_id": None,
                                "profile_type_name": None,
                                "steps": [
                                    {
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
                                ],
                                "alerts": [],
                            }
                        )
                    )
                ],
                [
                    _message(
                        json.dumps(
                            {
                                "name": "Bad recipe",
                                "description": None,
                                "public": False,
                                "profile_type_id": None,
                                "profile_type_name": None,
                                "steps": [
                                    {
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
                                ],
                                "alerts": [],
                            }
                        )
                    )
                ],
            ]
        )
        with patch("features.ai.services.AsyncOpenAI", forbidden_enum_factory):
            try:
                await generate_profile("Собери профиль с неверными enum")
            except ValueError as error:
                assert str(error) == "Модель не смогла собрать корректный профиль"
            else:
                raise AssertionError("Expected invalid enums to be rejected")

        missing_alert_text_factory = _FakeOpenAIFactory(
            [
                [
                    _message(
                        json.dumps(
                            {
                                "name": "Alert text test",
                                "description": "Короткое summary рецепта",
                                "public": False,
                                "profile_type_id": None,
                                "profile_type_name": None,
                                "steps": [
                                    {
                                        "id": None,
                                        "name": "Mash In",
                                        "order": 0,
                                        "controlType": "Target",
                                        "endType": "Manual",
                                        "durationType": "Manual",
                                        "operator": None,
                                        "length": None,
                                        "temperature": 67,
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
                                        "order": 1,
                                        "controlType": "Target",
                                        "endType": "Duration",
                                        "durationType": "Temperature",
                                        "operator": None,
                                        "length": 600,
                                        "temperature": 78,
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
                                        "order": 2,
                                        "controlType": "Target",
                                        "endType": "Manual",
                                        "durationType": "Start",
                                        "operator": None,
                                        "length": None,
                                        "temperature": 78,
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
                                        "order": 3,
                                        "controlType": "Target",
                                        "endType": "Duration",
                                        "durationType": "Temperature",
                                        "operator": None,
                                        "length": 3600,
                                        "temperature": 100,
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
                                                "alertText": "",
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
                                        "order": 4,
                                        "controlType": "Target",
                                        "endType": "Temperature",
                                        "durationType": "Start",
                                        "operator": None,
                                        "length": None,
                                        "temperature": 20,
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
                            }
                        )
                    )
                ],
                [_message(_VALID_WIZARD_JSON)],
            ]
        )
        with patch("features.ai.services.AsyncOpenAI", missing_alert_text_factory):
            repaired_profile = await generate_profile("Рецепт с хмелем и охлаждением после кипа.")
        assert repaired_profile["steps"][4]["alerts"][0]["alertText"]
        alert_retry_message = missing_alert_text_factory.requests[1]["messages"][-1]["content"]
        assert "У каждого step-alert обязателен непустой alertText" in alert_retry_message

        reset_factory = _FakeOpenAIFactory([[_message("Новая стартовая оценка.")]])
        with (
            patch("features.ai.services.SessionLocal", db.SessionLocal),
            patch("features.ai.services.AsyncOpenAI", reset_factory),
        ):
            reset_result = await reset_conversation(conversation["id"])
        assert reset_result["id"] == conversation["id"]
        assert [message["content"] for message in reset_result["messages"]] == [
            "Как идёт варка?",
            "Новая стартовая оценка.",
        ]
        assert _count_messages(db.SessionLocal, conversation["id"]) == 2
        assert reset_factory.requests[0]["temperature"] == LLM_TEMPERATURE

        with db.SessionLocal() as session:
            reset_row = session.get(AiConversation, conversation["id"])
            assert reset_row.summary is None
            assert reset_row.summary_through_message_id is None

        with db.SessionLocal() as session:
            summary_conversation = AiConversation(
                id="conv-summary",
                subject_type="recipe",
                subject_id="recipe-1",
                prompt_version="v1",
                summary=None,
                summary_through_message_id=None,
                created_at=datetime(2026, 7, 23, 13, 0, 0),
                updated_at=datetime(2026, 7, 23, 13, 0, 0),
            )
            session.add(summary_conversation)
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

        summary_factory = _FakeOpenAIFactory(
            [[_message("Сжатое резюме.")], [_message("Ответ с summary.")]]
        )
        with (
            patch("features.ai.services.SessionLocal", db.SessionLocal),
            patch("features.ai.services.AsyncOpenAI", summary_factory),
        ):
            await send_conversation_message("conv-summary", "Новый вопрос после длинной истории")
        assert len(summary_factory.requests) == 2
        assert summary_factory.requests[0]["messages"][0]["content"]
        assert "Старый вопрос 0" in summary_factory.requests[0]["messages"][1]["content"]
        main_system = summary_factory.requests[1]["messages"][0]["content"]
        assert "[CONVERSATION SUMMARY]" in main_system
        assert "Сжатое резюме." in main_system
        assert len(summary_factory.requests[1]["messages"]) == 1 + _RECENT_MESSAGES + 1

        with db.SessionLocal() as session:
            summarized = session.get(AiConversation, "conv-summary")
            assert summarized.summary == "Сжатое резюме."
            first_marker = summarized.summary_through_message_id
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

        second_summary_factory = _FakeOpenAIFactory(
            [[_message("Обновлённое резюме.")], [_message("Ещё один ответ.")]]
        )
        with (
            patch("features.ai.services.SessionLocal", db.SessionLocal),
            patch("features.ai.services.AsyncOpenAI", second_summary_factory),
        ):
            await send_conversation_message("conv-summary", "Ещё один новый вопрос")
        assert "Старый вопрос 0" not in second_summary_factory.requests[0]["messages"][1]["content"]
        with db.SessionLocal() as session:
            summarized = session.get(AiConversation, "conv-summary")
            assert summarized.summary_through_message_id > first_marker

        fallback_factory = _FakeOpenAIFactory([[_message("Ответ без summary.")]])
        with (
            patch("features.ai.services.SessionLocal", db.SessionLocal),
            patch(
                "features.ai.services._summarize_messages",
                side_effect=RuntimeError("summary failed"),
            ),
            patch("features.ai.services.AsyncOpenAI", fallback_factory),
        ):
            await send_conversation_message("conv-summary", "Проверь fallback summary")
        assert fallback_factory.requests[0]["messages"][-1]["content"] == "Проверь fallback summary"
        assert len(fallback_factory.requests[0]["messages"]) <= 1 + _SUMMARY_TRIGGER_MESSAGES + 1
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
