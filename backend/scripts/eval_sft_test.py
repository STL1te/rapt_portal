"""Evaluate the fine-tuned local model on the held-out SFT test split.

Replays each example's system+user messages against an OpenAI-compatible endpoint
(LM Studio) with the same json_schema response_format production uses, then scores:
  - parse: response is valid JSON
  - schema: SubmitRecipe validates
  - compile: compile_brewzilla_profile succeeds. Records whose own teacher spec fails
    the same check are scored `compile_na`, not charged to the model.
  - leaf match vs the teacher spec: flattened (path, value) leaves, numeric tolerance 1%

Results append to OUTPUT as JSONL (resumable by example index); a summary prints at
the end. Teacher specs aren't unique ground truth, so leaf match is a drift signal,
not an exact-accuracy metric.

Usage (from backend/). Outputs belong in data/sft/eval/, not next to the dataset:
  uv run python scripts\\eval_sft_test.py D:\\Work\\projects\\beer_knowledge\\data\\sft\\v6\\test.jsonl ^
    D:\\Work\\projects\\beer_knowledge\\data\\sft\\eval\\eval_student_v6_e4b_q8.jsonl ^
    --base-url http://localhost:1234/v1 --model gemma-4-e4b-it
"""

import argparse
import asyncio
import json
import sys
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))  # features.* when PYTHONPATH is unset

from openai import AsyncOpenAI
from pydantic import ValidationError

from features.ai.brewzilla_compiler import compile_brewzilla_profile
from features.ai.recipe_wizard import (
    _RECIPE_RESPONSE_FORMAT,
    SubmitRecipe,
    _strip_code_fences,
    _strip_empty_strings,
)


def _relaxed_schema(schema):
    """Strip llama.cpp-hostile keys but keep pydantic's natural `required` lists,
    so optional keys may be omitted — matching the SFT targets' key distribution
    (production's all-required variant forces keys the student never trained on)."""
    if isinstance(schema, dict):
        return {
            key: _relaxed_schema(value)
            for key, value in schema.items()
            if key not in ("minLength", "maxLength", "default")
        }
    if isinstance(schema, list):
        return [_relaxed_schema(value) for value in schema]
    return schema


_RELAXED_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "submit_recipe",
        "strict": True,
        "schema": _relaxed_schema(SubmitRecipe.model_json_schema(by_alias=True)),
    },
}


def _leaves(node, path=""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _leaves(value, f"{path}.{key}" if path else key)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _leaves(value, f"{path}[{index}]")
    else:
        yield path, node


# Free text: the teacher's wording is one of many correct ones, so exact agreement was
# never the target. Left in, they disagreed on ~95% of examples and dominated the mismatch
# ranking, hiding the fields that actually matter.
_FREE_TEXT_PATHS = frozenset({"recipe.notes", "recipe.name"})


def _leaf_match(reference: dict, candidate: dict) -> tuple[int, int, list[str]]:
    """(matched, total, mismatched paths) over the reference's leaves, minus free text."""
    candidate_leaves = dict(_leaves(candidate))
    matched, total, mismatches = 0, 0, []
    for path, expected in _leaves(reference):
        if path in _FREE_TEXT_PATHS:
            continue
        total += 1
        actual = candidate_leaves.get(path)
        if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
            ok = expected == actual or abs(actual - expected) <= abs(expected) * 0.01
        else:
            ok = actual == expected
        matched += ok
        if not ok:
            mismatches.append(path)
    return matched, total, mismatches


@lru_cache(maxsize=None)
def _reference_compiles(reference_json: str) -> bool:
    """Does the teacher's own spec survive the compile stage? Some sources state no mash
    schedule at all, and an all-grain recipe without one cannot be compiled — by anybody.
    Cached on the raw JSON so each test record is compiled once, not once per model."""
    try:
        submit = SubmitRecipe.model_validate(json.loads(reference_json))
        compile_brewzilla_profile(submit.recipe, submit.brewzilla_overrides)
    except Exception:  # noqa: BLE001 — any failure means "not a fair check", not a crash
        return False
    return True


async def _run_one(
    client: AsyncOpenAI,
    model: str,
    example: dict,
    timeout: float,
    response_format: dict,
    strip_empty: bool,
) -> dict:
    messages = [m for m in example["messages"] if m["role"] != "assistant"]
    reference = json.loads(example["messages"][-1]["content"])
    record = {}
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0,
            max_tokens=16_384,
            timeout=timeout,
            # Gemma-4 12B keeps reasoning even after SFT: the trace lands in `reasoning`,
            # leaving `content` empty, or runs past the context window. E4B stops on its own.
            extra_body={"reasoning_effort": "none"},
            **({"response_format": response_format} if response_format else {}),
        )
        raw = response.choices[0].message.content or ""
    except Exception as error:  # noqa: BLE001 — record and move on, eval must finish
        return {"status": "request_error", "error": f"{type(error).__name__}: {error}"}
    try:
        spec = json.loads(_strip_code_fences(raw))
    except json.JSONDecodeError as error:
        return {"status": "parse_error", "error": str(error), "raw": raw[:500]}
    if strip_empty:
        spec = _strip_empty_strings(spec)
    spec.setdefault("brewzilla_overrides", None)
    try:
        submit = SubmitRecipe.model_validate(spec)
    except ValidationError as error:
        first = error.errors()[0]
        return {
            "status": "schema_error",
            "error": f"{'.'.join(map(str, first['loc']))}: {first['msg']}",
        }
    try:
        compile_brewzilla_profile(submit.recipe, submit.brewzilla_overrides)
    except Exception as error:  # noqa: BLE001 — compiler raises plain ValueError/TypeError
        # Some sources state no mash schedule at all, so the teacher's own spec does not
        # compile either. Charging that to the student measures the corpus, not the model.
        record = (
            {"status": "compile_na", "error": f"{type(error).__name__}: {error}"}
            if not _reference_compiles(example["messages"][-1]["content"])
            else {"status": "compile_error", "error": f"{type(error).__name__}: {error}"}
        )
    else:
        record = {"status": "ok"}
    matched, total, mismatches = _leaf_match(reference, spec)
    record.update({"leaf_matched": matched, "leaf_total": total, "mismatches": mismatches})
    return record


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("test_set", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--base-url", default="http://localhost:1234/v1")
    parser.add_argument("--model", default="gemma-4-e4b-it")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--relaxed-schema",
        action="store_true",
        help="don't force optional keys into `required` (matches SFT target distribution)",
    )
    parser.add_argument(
        "--strip-empty",
        action="store_true",
        help="drop empty-string values before validation (grammar-forced keys the "
        "model had no value for)",
    )
    parser.add_argument(
        "--no-response-format",
        action="store_true",
        help="send no response_format at all. Ollama renders the schema into the "
        "prompt as a tool definition for tool-capable templates, which derails "
        "a student trained to answer with bare JSON (empty content, prose in "
        "`reasoning`). The SFT target IS the grammar, so unconstrained is fine.",
    )
    args = parser.parse_args()
    if args.no_response_format:
        response_format = None
    else:
        response_format = (
            _RELAXED_RESPONSE_FORMAT if args.relaxed_schema else _RECIPE_RESPONSE_FORMAT
        )

    examples = [
        json.loads(line)
        for line in args.test_set.read_text(encoding="utf-8").split("\n")
        if line.strip()
    ]
    if args.limit:
        examples = examples[: args.limit]
    done = set()
    if args.output.exists():
        done = {
            json.loads(line)["index"]
            for line in args.output.read_text(encoding="utf-8").split("\n")
            if line.strip()
        }

    client = AsyncOpenAI(base_url=args.base_url, api_key="not-needed")
    semaphore = asyncio.Semaphore(args.concurrency)
    lock = asyncio.Lock()

    async def worker(index: int, example: dict) -> None:
        async with semaphore:
            record = await _run_one(
                client, args.model, example, args.timeout, response_format, args.strip_empty
            )
        record["index"] = index
        async with lock:
            with args.output.open("a", encoding="utf-8") as sink:
                sink.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"[{index}] {record['status']}", record.get("error", ""), flush=True)

    await asyncio.gather(*(worker(i, ex) for i, ex in enumerate(examples) if i not in done))

    results = [
        json.loads(line)
        for line in args.output.read_text(encoding="utf-8").split("\n")
        if line.strip()
    ]
    statuses = {}
    for record in results:
        statuses[record["status"]] = statuses.get(record["status"], 0) + 1
    print("\n=== summary ===")
    for status, count in sorted(statuses.items()):
        print(f"{status}: {count}/{len(results)}")
    scored = [r for r in results if "leaf_total" in r]
    if scored:
        rates = sorted(r["leaf_matched"] / r["leaf_total"] for r in scored)
        print(
            f"leaf match: median {rates[len(rates) // 2]:.0%}, "
            f"p10 {rates[int(len(rates) * 0.1)]:.0%}, min {rates[0]:.0%}"
        )
        worst: dict[str, int] = {}
        for record in scored:
            for path in record["mismatches"]:
                worst[path] = worst.get(path, 0) + 1
        print("top mismatched paths:")
        for path, count in sorted(worst.items(), key=lambda kv: -kv[1])[:15]:
            print(f"  {count:3d}  {path}")


if __name__ == "__main__":
    asyncio.run(main())
