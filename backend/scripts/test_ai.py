"""Small offline check for the OpenAI-compatible LLM request."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from features.ai.services import DEFAULT_INSTRUCTIONS, TOOLS, _sample, assess


class _Client:
    def __init__(self):
        self.chat = SimpleNamespace(completions=self)
        self.request = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def create(self, **kwargs):
        self.request = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Done.", tool_calls=None))]
        )


class _ToolClient(_Client):
    def __init__(self):
        super().__init__()
        self.responses = [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    id="call-1",
                                    function=SimpleNamespace(
                                        name="search_sessions",
                                        arguments='{"query":"tropicana","kind":"brew"}',
                                    ),
                                )
                            ],
                            model_dump=lambda **_: {
                                "role": "assistant",
                                "tool_calls": [{"id": "call-1"}],
                            },
                        )
                    )
                ]
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(message=SimpleNamespace(content="Compared.", tool_calls=None))
                ]
            ),
        ]

    async def create(self, **kwargs):
        self.request = kwargs
        return self.responses.pop(0)


async def main() -> None:
    telemetry = _sample(
        [SimpleNamespace(timestamp="2026-07-22", gravity=1012.0, temperature=20.0, battery=92.0)],
        ("timestamp", "gravity", "temperature"),
    )
    assert telemetry == [{"timestamp": "2026-07-22", "gravity": 1012.0, "temperature": 20.0}]

    client = _Client()
    with patch("features.ai.services.AsyncOpenAI", return_value=client):
        answer = await assess(
            "brew",
            "11111111-1111-1111-1111-111111111111",
            '{"current_session":{}}',
            None,
            [{"role": "user", "content": "Clarify risks."}],
        )

    assert answer == "Done."
    assert client.request["model"]
    assert client.request["messages"][1] == {"role": "user", "content": "Clarify risks."}
    assert DEFAULT_INSTRUCTIONS[("brew", False)] in client.request["messages"][2]["content"]
    assert (
        '<current_session_context>{"current_session":{}}</current_session_context>'
        in client.request["messages"][2]["content"]
    )
    assert {tool["function"]["name"] for tool in TOOLS} == {
        "list_brew_sessions",
        "list_fermentation_sessions",
        "search_sessions",
        "get_session_context",
    }

    tool_client = _ToolClient()
    with (
        patch("features.ai.services.AsyncOpenAI", return_value=tool_client),
        patch("features.ai.services._run_tool", return_value={"sessions": []}) as run_tool,
    ):
        answer = await assess("brew", "current", "{}", "Compare with tropicana")
    assert answer == "Compared."
    run_tool.assert_called_once_with(
        "current", "search_sessions", {"query": "tropicana", "kind": "brew"}
    )

    done_client = _Client()
    with patch("features.ai.services.AsyncOpenAI", return_value=done_client):
        await assess("brew", "id", '{"current_session":{}}', None, completed=True)
    assert DEFAULT_INSTRUCTIONS[("brew", True)] in done_client.request["messages"][1]["content"]


if __name__ == "__main__":
    asyncio.run(main())
