"""Replay the SFT test split against a Claude model as a teacher candidate.

Goes through the native Messages API, not Anthropic's OpenAI-compatible endpoint: that
one ignores response_format and reasoning_effort and has no prompt caching. There is no
grammar either way: structured outputs and strict tools reject the SubmitRecipe schema
("compiled grammar is too large", strict and relaxed alike). Plain JSON in the text failed
on its own: the prompt calls the schema authoritative but never contains it, so the model
added BeerJSON fields ours forbids (`ibu_estimate`, culture `temperature_range`) and, with
thinking off, reasoned in prose ahead of the JSON. So the spec comes back as the input of a
non-strict `submit_recipe` tool: the model sees the schema and the API parses the JSON.
Scoring is
eval_sft_test's `_score`, so the numbers sit on the same scale as the students' — here
they read as agreement with the v6 teacher's (gpt-5.6-terra) conventions.

Each record also keeps the request's token usage; the summary prints the cost.

Usage (from backend/, key in ANTHROPIC_API_KEY):
  uv run --with anthropic python scripts\\eval_claude_teacher.py ^
    D:\\Work\\projects\\beer_knowledge\\data\\sft\\v6\\test.jsonl ^
    D:\\Work\\projects\\beer_knowledge\\data\\sft\\eval\\teacher_v6_claude-sonnet-5-5.jsonl ^
    --model claude-sonnet-5-5
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))  # features.* when PYTHONPATH is unset

import anthropic
from eval_sft_test import _print_summary, _score

from features.ai.recipe_wizard import SubmitRecipe

_TOOL = {
    "name": "submit_recipe",
    "description": "Submit the extracted recipe. The tool input IS the submit_recipe object: "
    'its top-level keys are "recipe" and "brewzilla_overrides".',
    "input_schema": SubmitRecipe.model_json_schema(by_alias=True),
}

# $/MTok (input, output). Cache writes bill 1.25x input, cache reads 0.1x.
_PRICES = {
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-haiku-5-5": (0.10, 0.50),
}


def _thinking(model: str, mode: str) -> dict:
    if mode == "adaptive":
        return {"type": "adaptive"}
    # Sonnet 5.5 rejects "disabled"; between_tools is its thinking-off switch.
    return {"type": "between_tools"} if model == "claude-sonnet-5-5" else {"type": "disabled"}


def _cost(model: str, usage: dict) -> float:
    price_in, price_out = _PRICES[model]
    return (
        usage["input_tokens"] * price_in
        + usage["cache_creation_input_tokens"] * price_in * 1.25
        + usage["cache_read_input_tokens"] * price_in * 0.1
        + usage["output_tokens"] * price_out
    ) / 1e6


async def _run_one(client, args, example: dict) -> dict:
    system, user = example["messages"][0]["content"], example["messages"][1]["content"]
    request = {
        "model": args.model,
        "max_tokens": 16_000,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user}],
        "thinking": _thinking(args.model, args.thinking),
        # auto: Sonnet 5.5 rejects a forced tool_choice; the prompt already demands the call.
        "tools": [_TOOL],
        "tool_choice": {"type": "auto"},
    }
    if args.effort:
        request["output_config"] = {"effort": args.effort}
    try:
        response = await client.messages.create(**request)
    except anthropic.APIError as error:
        return {"status": "request_error", "error": f"{type(error).__name__}: {error}"}
    usage = {
        key: getattr(response.usage, key) or 0
        for key in (
            "input_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
            "output_tokens",
        )
    }
    meta = {"stop_reason": response.stop_reason, "usage": usage}
    if response.stop_reason == "refusal":
        return {"status": "refusal", **meta}
    call = next((block for block in response.content if block.type == "tool_use"), None)
    if call is None:
        text = "".join(block.text for block in response.content if block.type == "text")
        return {"status": "no_tool_call", "raw": text[:500], **meta}
    spec = call.input
    # Transport slips, not content: the prompt calls the whole reply "one submit_recipe
    # object", so Sonnet 5 passes it as the `recipe` argument, and both models now and then
    # send `recipe` as a JSON string — of the recipe alone, or of the recipe plus the rest
    # of the object (`{...}, "brewzilla_overrides": null}`), Sonnet 5.5 at times with its
    # raw tool-call markup (`</invoke>`) leaked onto the end. Counted in `unwrapped`.
    if isinstance(spec.get("recipe"), str):
        text = re.sub(r"(\s*</\w+>)+\s*$", "", spec.pop("recipe"))
        for wrapped in ('{"recipe": ' + text + "}", '{"recipe": ' + text):
            try:
                spec = {**spec, **json.loads(wrapped)}
                break
            except json.JSONDecodeError:
                continue
        else:
            return {"status": "parse_error", "raw": text, **meta}
        meta["unwrapped"] = "string"
    if set(spec) == {"recipe"} and "recipe" in (spec["recipe"] or {}):
        spec = spec["recipe"]
        meta["unwrapped"] = "nested"
    # The spec is kept: judging a disagreement with the reference needs the values.
    return {**_score(json.dumps(spec), example, strip_empty=False), **meta, "spec": spec}


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("test_set", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", required=True, choices=sorted(_PRICES))
    parser.add_argument("--thinking", choices=["off", "adaptive"], default="off")
    parser.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    examples = [
        json.loads(line)
        for line in args.test_set.read_text(encoding="utf-8").split("\n")
        if line.strip()
    ][: args.limit]
    done = set()
    if args.output.exists():
        done = {
            json.loads(line)["index"]
            for line in args.output.read_text(encoding="utf-8").split("\n")
            if line.strip()
        }

    client = anthropic.AsyncAnthropic(max_retries=6)
    semaphore = asyncio.Semaphore(args.concurrency)
    lock = asyncio.Lock()

    async def worker(index: int, example: dict) -> None:
        async with semaphore:
            record = await _run_one(client, args, example)
        record["index"] = index
        async with lock:
            with args.output.open("a", encoding="utf-8") as sink:
                sink.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"[{index}] {record['status']}", record.get("error", ""), flush=True)

    await asyncio.gather(*(worker(i, ex) for i, ex in enumerate(examples) if i not in done))
    _print_summary(args.output)

    usages = [
        json.loads(line)["usage"]
        for line in args.output.read_text(encoding="utf-8").split("\n")
        if line.strip() and '"usage"' in line
    ]
    if usages:
        total = sum(_cost(args.model, u) for u in usages)
        out = sorted(u["output_tokens"] for u in usages)
        print(
            f"cost: ${total:.2f} for {len(usages)} rows, ${total / len(usages):.4f}/row "
            f"(batch API halves it); output tokens median {out[len(out) // 2]}, max {out[-1]}"
        )


if __name__ == "__main__":
    asyncio.run(main())
