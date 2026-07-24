"""Run the recipe wizard against a prefix (or seeded-random subset) of a JSONL corpus."""

import argparse
import asyncio
import json
import random
from pathlib import Path

from pydantic import ValidationError

from features.ai.beerjson_models import to_beerjson_document
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


def _select(rows: list[dict], count: int, seed: int | None) -> list[tuple[int, dict]]:
    """First `count` rows in corpus order, so --count N is a prefix and larger counts
    are supersets. With --shuffle SEED, rows are shuffled by seed first: same seed stays
    nested and resumable, a different seed draws a different subset."""
    ordered = list(enumerate(rows))
    if seed is not None:
        random.Random(seed).shuffle(ordered)
    return ordered[:count]


_READY = ("ok", "ok_repaired")


def _load_results(path: Path) -> dict[int, dict]:
    """Existing results keyed by corpus index (last line wins per index)."""
    if not path.exists():
        return {}
    return {
        result["index"]: result
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for result in [json.loads(line)]
    }


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
    parser.add_argument("--shuffle", type=int, metavar="SEED", help="draw a random subset")
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
        else _select(rows, args.count, args.shuffle)
    )
    results = _load_results(args.output)
    ready = {index for index, result in results.items() if result["status"] in _READY}
    pending = [(index, row) for index, row in selected if index not in ready]
    skipped = len(selected) - len(pending)
    if skipped:
        print(f"resuming: {skipped}/{len(selected)} already ready, {len(pending)} to run", flush=True)

    semaphore = asyncio.Semaphore(args.concurrency)
    completed = 0
    log = args.output.open("a", encoding="utf-8")  # crash-safe append; collapsed at the end

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
                        submit, profile = await asyncio.wait_for(
                            _generate_once(source, None, None, retry=False, user_overrides=None),
                            timeout=args.timeout,
                        )
                    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as error:
                        result["first_errors"] = _error_chain(error)
                        correction = (
                            "Return submit_recipe again as one complete corrected JSON object. "
                            "Preserve every explicit source value and the source language. "
                            f"The previous attempt failed:\n{error}"
                        )
                        submit, profile = await asyncio.wait_for(
                            _generate_once(
                                source, correction, None, retry=True, user_overrides=None
                            ),
                            timeout=args.timeout,
                        )
                result.update(
                    status="ok_repaired" if "first_errors" in result else "ok",
                    spec=submit.model_dump(by_alias=True, exclude_none=True),
                    recipe=to_beerjson_document(submit.recipe),
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
        results[index] = result
        log.write(json.dumps(result, ensure_ascii=False) + "\n")
        log.flush()
        completed += 1
        print(f"{completed}/{len(pending)} {result['status']} index={index}", flush=True)

    try:
        await asyncio.gather(*(evaluate(index, row) for index, row in pending))
    finally:
        log.close()

    # Collapse the append log (may hold duplicate retried indices) into a clean file.
    ordered = sorted(results.values(), key=lambda result: result["source_length"])
    args.output.write_text(
        "".join(json.dumps(result, ensure_ascii=False) + "\n" for result in ordered),
        encoding="utf-8",
    )
    counts = {
        status: sum(result["status"] == status for result in ordered)
        for status in sorted({result["status"] for result in ordered})
    }
    print(json.dumps(counts, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
