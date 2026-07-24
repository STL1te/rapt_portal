"""Run the recipe wizard against a deterministic sample from a JSONL corpus."""

import argparse
import asyncio
import json
from pathlib import Path

from pydantic import ValidationError

from features.ai.recipe_wizard import _generate_once
from features.ai.router import RecipeWizardRequest


def _source(row: dict) -> str:
    header = (
        f"Название: {row['name']}\n"
        f"Стиль: {row['style_full']}\n"
        f"Тип: {row['type']}\n"
        f"Объём: {row['volume']}\n"
    )
    return f"{header}{row['full_description']}"


def _sample(rows: list[dict], count: int) -> list[tuple[int, dict]]:
    ordered = sorted(enumerate(rows), key=lambda item: len(_source(item[1])))
    if count >= len(ordered):
        return ordered
    if count == 1:
        return [ordered[len(ordered) // 2]]
    return [ordered[round(i * (len(ordered) - 1) / (count - 1))] for i in range(count)]


def _error_chain(error: Exception) -> list[str]:
    errors = []
    current: BaseException | None = error
    while current and len(errors) < 5:
        errors.append(f"{type(current).__name__}: {current}")
        current = current.__cause__
    return errors


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--count", type=int, default=36)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--indices", type=int, nargs="*")
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()

    rows = [
        json.loads(line)
        for line in args.corpus.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    selected = (
        [(index, rows[index]) for index in args.indices]
        if args.indices
        else _sample(rows, min(args.count, len(rows)))
    )
    semaphore = asyncio.Semaphore(args.concurrency)
    completed = 0
    results: list[dict] = []

    async def evaluate(index: int, row: dict) -> None:
        nonlocal completed
        source = _source(row)
        result = {
            "index": index,
            "name": row["name"],
            "type": row["type"],
            "source_length": len(source),
            "url": row["url"],
        }
        try:
            RecipeWizardRequest(description=source)
        except ValidationError as error:
            result.update(status="input_too_long", errors=_error_chain(error))
        else:
            try:
                async with semaphore:
                    try:
                        spec, profile = await asyncio.wait_for(
                            _generate_once(source, None, None, retry=False),
                            timeout=args.timeout,
                        )
                    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as error:
                        result["first_errors"] = _error_chain(error)
                        correction = (
                            "Call submit_recipe_spec again with a complete corrected "
                            "specification. Preserve every explicit source value and the source "
                            f"language. The previous attempt failed:\n{error}"
                        )
                        spec, profile = await asyncio.wait_for(
                            _generate_once(source, correction, None, retry=True),
                            timeout=args.timeout,
                        )
                result.update(
                    status="ok_repaired" if "first_errors" in result else "ok",
                    spec=spec.model_dump(exclude_unset=True),
                    steps=[
                        {
                            "name": step["name"],
                            "temperature": step["temperature"],
                            "length": step["length"],
                            "alerts": step["alerts"],
                        }
                        for step in profile["steps"]
                    ],
                )
            except Exception as error:
                result.update(status="error", errors=_error_chain(error))
        results.append(result)
        completed += 1
        print(f"{completed}/{len(selected)} {result['status']} index={index}", flush=True)

    await asyncio.gather(*(evaluate(index, row) for index, row in selected))
    results.sort(key=lambda result: result["source_length"])
    args.output.write_text(
        "".join(json.dumps(result, ensure_ascii=False) + "\n" for result in results),
        encoding="utf-8",
    )
    counts = {
        status: sum(result["status"] == status for result in results)
        for status in sorted({result["status"] for result in results})
    }
    print(json.dumps(counts, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
