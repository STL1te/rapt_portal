"""Run the recipe wizard against a prefix (or seeded-random subset) of a JSONL corpus."""

import argparse
import asyncio
import json
import random
import re
from pathlib import Path

from pydantic import ValidationError

from features.ai.beerjson_models import to_beerjson_document
from features.ai.recipe_wizard import _generate_once
from features.ai.router import RecipeWizardRequest


async def _strict_generate(source: str, correction: str | None, *, retry: bool):
    """Distillation-grade generation: specs are training targets, so unresolved
    semantic mismatches are failures here even though production returns them
    best-effort."""
    submit, profile, semantic_errors = await _generate_once(
        source, correction, None, retry=retry, user_overrides=None
    )
    if semantic_errors:
        raise ValueError("Recipe mismatches:\n- " + "\n- ".join(semantic_errors))
    return submit, profile


def _source(row: dict) -> str:
    if "BrewMethod" in row:  # Brewer's Friend (English) corpus
        return _source_en(row)
    header = (
        f"Название: {row['name']}\n"
        f"Стиль: {row['style_full']}\n"
        f"Тип: {row['type']}\n"
        f"Объём: {row['volume']}\n"
    )
    return f"{header}{row['full_description']}"


_EN_HEADER_FIELDS = (
    ("Style", "Style"),
    ("BrewMethod", "Method"),
    ("Size(L)", "Batch Size (L)"),
    ("BoilSize", "Boil Size (L)"),
    ("BoilTime", "Boil Time (min)"),
    ("OG", "OG"),
    ("FG", "FG"),
    ("ABV", "ABV %"),
    ("IBU", "IBU"),
    ("Color", "Color (SRM)"),
    ("Efficiency", "Efficiency %"),
    ("SugarScale", "Sugar Scale"),
    ("MashThickness", "Mash Thickness"),
    ("PrimaryTemp", "Primary Temp (C)"),
    ("PitchRate", "Pitch Rate"),
    ("PrimingMethod", "Priming Method"),
    ("PrimingAmount", "Priming Amount"),
)


def _source_en(row: dict) -> str:
    lines = [f"Name: {row['Name']}"]
    lines += [
        f"{label}: {row[key]}"
        for key, label in _EN_HEADER_FIELDS
        if row.get(key) not in (None, "", "N/A")
    ]
    lines.append("Ingredients:")
    lines += [f"- {item}" for item in row["ingredients"]]
    lines += [part for part in row.get("instructions") or [] if part]
    if row.get("notes"):
        lines.append(row["notes"])
    return "\n".join(lines)


def _meta(row: dict) -> tuple[str, str]:
    """(name, type) for the result record, per corpus format."""
    if "BrewMethod" in row:
        return row["Name"], row["BrewMethod"]
    return row["name"], row["type"]


def _is_grain(row: dict) -> bool:
    if "BrewMethod" in row:
        return row["BrewMethod"] in ("All Grain", "BIAB")
    return row["type"] == "Зерновой"


def _has_mash_info(row: dict) -> bool:
    """Brewer's Friend authors often leave the mash process empty; such grain rows are
    doomed by construction (the compiler requires a mash, the validator forbids an
    invented one), so skip them before spending LLM calls.
    ponytail: regex heuristic, validated on a 500-row run (drops 90/101 doomed rows,
    loses 5/330 good ones); tune the pattern if the loss rate grows."""
    if "BrewMethod" not in row:
        return True
    return bool(re.search(r"(?is)mash(?! thickness)[^|]{0,60}?\d", _source_en(row)))


def _select(pairs: list[tuple[int, dict]], count: int, seed: int | None) -> list[tuple[int, dict]]:
    """First `count` (index, row) pairs in corpus order, so --count N is a prefix and
    larger counts are supersets. With --shuffle SEED, pairs are shuffled by seed first:
    same seed stays nested and resumable, a different seed draws a different subset."""
    ordered = list(pairs)
    if seed is not None:
        random.Random(seed).shuffle(ordered)
    return ordered[:count]


_READY = ("ok", "ok_repaired")


def _load_results(path: Path) -> dict[int, dict]:
    """Existing results keyed by corpus index (last line wins per index)."""
    if not path.exists():
        return {}
    # split("\n"), not splitlines(): JSON strings may legally contain raw U+2028/U+2029,
    # which splitlines() treats as line breaks, tearing lines apart mid-string.
    return {
        result["index"]: result
        for line in path.read_text(encoding="utf-8").split("\n")
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
    parser.add_argument(
        "--skip-errors",
        action="store_true",
        help="don't retry rows already recorded as status=error (e.g. structurally broken recipes)",
    )
    args = parser.parse_args()

    rows = [
        json.loads(line)
        for line in args.corpus.read_text(encoding="utf-8").split("\n")
        if line.strip()
    ]
    # Corpus indices stay stable across runs (stored as "index" in the output and used
    # for resume/--skip-errors), so filter by type without renumbering.
    grain_pairs = [(index, row) for index, row in enumerate(rows) if _is_grain(row)]
    selected = (
        [(index, rows[index]) for index in args.indices]
        if args.indices
        else _select(grain_pairs, args.count, args.shuffle)
    )
    results = _load_results(args.output)
    ready_statuses = _READY + ("error",) if args.skip_errors else _READY
    ready = {index for index, result in results.items() if result["status"] in ready_statuses}
    # Explicit --indices bypass the mash prefilter: an explicit request wins.
    pending = [
        (index, row)
        for index, row in selected
        if index not in ready and (args.indices or _has_mash_info(row))
    ]
    skipped = len(selected) - len(pending)
    if skipped:
        no_mash = (
            0
            if args.indices
            else sum(1 for index, row in selected if index not in ready and not _has_mash_info(row))
        )
        print(
            f"resuming: {skipped - no_mash}/{len(selected)} already ready, "
            f"{no_mash} prefiltered (no mash info), {len(pending)} to run",
            flush=True,
        )

    semaphore = asyncio.Semaphore(args.concurrency)
    completed = 0
    log = args.output.open("a", encoding="utf-8")  # crash-safe append; collapsed at the end

    async def evaluate(index: int, row: dict) -> None:
        nonlocal completed
        source = _source(row)
        name, row_type = _meta(row)
        result = {
            "index": index,
            "name": name,
            "type": row_type,
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
                            _strict_generate(source, None, retry=False),
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
                            _strict_generate(source, correction, retry=True),
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
