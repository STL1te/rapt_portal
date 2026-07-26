"""Rewrite accepted distillation sources into hand-typed free-form recipe drafts.

The distillation corpus is machine-exported prose; real users type messy shorthand
(caps headers, abbreviations, mixed units). For each accepted (source, spec) pair the
frontier model rewrites the source in one of several hand-typed styles, preserving
every brewing value; the existing spec stays the training target. The semantic
validator then checks the spec against the rewritten text — rewrites that lost or
changed values are rejected.

Output rows are build_sft_dataset.py-compatible ({index, name, status, spec}) plus a
"rewrite" field the builder uses as the user turn instead of _source(). Reruns skip
"ok" rows and retry rejected ones. LLM settings come from backend/.env (frontier).

Usage (from backend/, or via run_freeform.cmd):
  uv run python scripts\\freeform_rewrite.py RESULTS CORPUS OUTPUT ^
    --exclude VAL_JSONL TEST_JSONL --count 50
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))  # features.* when PYTHONPATH is unset

from pydantic import ValidationError

from evaluate_recipe_wizard import _READY, _load_results, _meta, _source
from features.ai.recipe_wizard import SubmitRecipe, _semantic_recipe_errors
from features.ai.services import _run_chat_completion

_STYLES = (
    "CAPS section headers (МАЛТ/СОЛОД, ХМЕЛЬ, ДРОЖЖИ or the source-language equivalents), "
    "exclamation marks, dashes between name and amount, degree signs written sloppily "
    "(67*, 78 С), grams as 'гр'/'g'.",
    "One dense paragraph in plain sentences, values inline, minimal punctuation, "
    "no section headers at all.",
    "Bullet list with '-', heavy abbreviations (а/к or AA for alpha acids, 'мин' or 'min'), "
    "units occasionally omitted where obvious from context.",
    "Chat-message style: short lowercase lines, parenthetical asides, a couple of typos "
    "in ordinary words (never in numbers or ingredient names).",
    "Numbered steps in brewing order (mash rests, boil with hop timings, fermentation), "
    "ingredients mentioned inside the steps rather than in a separate list.",
)

# Partial drafts: real users often paste only a fragment (just the mash rests, just
# the grain bill). Each cut names the sections to keep and a spec filter; the cut
# spec becomes the training target so the model learns to omit what wasn't given.
_PARTIAL_CUTS = (
    ("the mash rests (temperatures/durations) and the boil time", ("mash", "boil")),
    ("the recipe name and the ingredient lists (malts, hops, yeast)", ("name", "ingredients")),
    ("the mash rests, the boil time and the hop additions with timings", ("mash", "boil", "hops")),
)


def _cut_spec(spec: dict, keys: tuple[str, ...]) -> dict | None:
    """Partial spec for a partial draft; None when the source lacks the sections."""
    recipe = {key: spec["recipe"][key] for key in keys if key != "hops" and spec["recipe"].get(key)}
    if "hops" in keys:
        hops = (spec["recipe"].get("ingredients") or {}).get("hop_additions")
        if hops:
            recipe["ingredients"] = {"hop_additions": hops}
    # a cut that lost its defining section teaches nothing — mash/ingredients anchor the cut
    if "mash" in keys and "mash" not in recipe:
        return None
    if "ingredients" in keys and "ingredients" not in recipe:
        return None
    return {"recipe": recipe, "brewzilla_overrides": None}


_SYSTEM = """You convert a structured beer recipe export into a realistic hand-typed draft — \
the way a homebrewer quickly types a recipe into a chat or notes app.

Rules:
- Write in the SAME language as the source.
- Preserve every concrete brewing fact: recipe name, style, batch and water volumes, every \
ingredient with its amount, alpha acids, every hop/spice addition with its timing, every mash \
rest temperature and duration, boil time, yeast, OG/FG/ABV/IBU if stated, fermentation \
temperatures. Numbers must not change (reformatting is fine: 0.5 kg -> 500 г).
- Copy ingredient, hop, yeast and producer names character-for-character from the source \
(same spelling, same punctuation, no added dashes or spaces).
- Never mix languages: headers, units and abbreviations must be in the source's language. \
Russian words in the style notes below are examples for Russian sources only — for an \
English source every word you add must be English.
- Keep the essential meaning of author notes; compressing them is fine.
- Do NOT invent facts, ingredients, steps or numbers. Do NOT drop any.
- Output ONLY the rewritten recipe text, no preamble or commentary.

Style for this rewrite: {style}{partial}"""

_PARTIAL_RULE = """

This draft is intentionally PARTIAL — the brewer is only sharing part of the recipe. \
Include ONLY {sections}. Omit every other fact (volumes, gravities, notes, the rest of \
the recipe) entirely, as if the brewer never typed them."""


def _excluded_specs(paths: list[Path]) -> set[str]:
    """Compact spec dumps of frozen val/test examples: rewriting those rows would leak
    their targets into train."""
    dumps = set()
    for path in paths:
        for line in path.read_text(encoding="utf-8").split("\n"):
            if line.strip():
                dumps.add(json.loads(line)["messages"][-1]["content"])
    return dumps


_CYRILLIC = re.compile("[а-яА-ЯёЁ]")
_EXPECTED_ACTUAL = re.compile(r'expected "(.*?)", actual "(.*?)"')


def _cosmetic(error: str) -> bool:
    """True when the validator's expected/actual differ only in punctuation or case
    (e.g. 'Fermentis Сафале US-05' vs 'Fermentis - Сафале US-05'). The spec is the
    target here and the rewrite is derived from it, so such diffs are not real losses."""
    pair = _EXPECTED_ACTUAL.search(error)
    if not pair:
        return False
    normalized = [re.sub(r"[\W_]+", "", value).casefold() for value in pair.groups()]
    return normalized[0] == normalized[1]


async def _rewrite_one(
    index: int, row: dict, spec: dict, style: str, sections: str | None
) -> dict:
    source = _source(row).strip()
    partial_rule = _PARTIAL_RULE.format(sections=sections) if sections else ""
    rewrite = await _run_chat_completion(
        [
            {"role": "system", "content": _SYSTEM.format(style=style, partial=partial_rule)},
            {"role": "user", "content": source},
        ],
        tools=None,
        current_session_id=None,
        temperature=0.7,
        max_tokens=8_192,
    )
    rewrite = rewrite.strip()
    # the frontier sometimes copies Russian tokens from the style notes into
    # English sources; a language flip is always a reject, retried on rerun
    if _CYRILLIC.search(rewrite) and not _CYRILLIC.search(source):
        return {"status": "language", "rewrite": rewrite}
    submit = SubmitRecipe.model_validate(spec)
    errors = [e for e in await _semantic_recipe_errors(rewrite, submit) if not _cosmetic(e)]
    if errors:
        return {"status": "mismatch", "rewrite": rewrite, "errors": errors}
    return {"status": "ok", "rewrite": rewrite}


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("results", type=Path, help="distillation results jsonl")
    parser.add_argument("corpus", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--exclude", type=Path, nargs="*", default=[],
                        help="frozen split files (val/test) whose recipes must not be rewritten")
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument(
        "--partial", action="store_true",
        help="produce partial drafts (mash-only, ingredients-only, ...) with the spec "
             "cut to match; use a separate output file from the full-rewrite run",
    )
    args = parser.parse_args()

    rows = [
        json.loads(line)
        for line in args.corpus.read_text(encoding="utf-8").split("\n")
        if line.strip()
    ]
    excluded = _excluded_specs(args.exclude)
    done = {
        index
        for index, record in _load_results(args.output).items()
        if record["status"] == "ok"
    }

    candidates = []
    for index, result in sorted(_load_results(args.results).items()):
        if result["status"] not in _READY or index in done:
            continue
        spec = result["spec"]
        spec.setdefault("brewzilla_overrides", None)
        if json.dumps(spec, ensure_ascii=False, separators=(",", ":")) in excluded:
            continue
        try:
            SubmitRecipe.model_validate(spec)
        except ValidationError:
            continue  # stale schema, same skip as build_sft_dataset
        name, _ = _meta(rows[index])
        if name != result["name"]:
            raise SystemExit(f"index {index}: results say {result['name']!r}, corpus {name!r}")
        sections = None
        if args.partial:
            sections, keys = _PARTIAL_CUTS[index % len(_PARTIAL_CUTS)]
            spec = _cut_spec(spec, keys)
            if spec is None:  # source lacks the cut's anchor section
                continue
        candidates.append((index, result, spec, sections))
        if len(candidates) >= args.count:
            break

    print(f"{len(candidates)} rows to rewrite ({len(done)} already ok, {len(excluded)} frozen)")
    semaphore = asyncio.Semaphore(args.concurrency)
    lock = asyncio.Lock()

    async def worker(index: int, result: dict, spec: dict, sections: str | None) -> None:
        style = _STYLES[index % len(_STYLES)]
        async with semaphore:
            try:
                record = await _rewrite_one(index, rows[index], spec, style, sections)
            except Exception as error:  # noqa: BLE001 — record and keep the run going
                record = {"status": "error", "error": f"{type(error).__name__}: {error}"}
        # partial mode: the cut spec is the training target, not the full one
        record.update({"index": index, "name": result["name"], "spec": spec})
        async with lock:
            with args.output.open("a", encoding="utf-8") as sink:
                sink.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"[{index}] {record['status']}", (record.get("errors") or [""])[0], flush=True)

    await asyncio.gather(*(worker(*candidate) for candidate in candidates))

    final = _load_results(args.output)
    counts: dict[str, int] = {}
    for record in final.values():
        counts[record["status"]] = counts.get(record["status"], 0) + 1
    print("total:", ", ".join(f"{status}={count}" for status, count in sorted(counts.items())))


if __name__ == "__main__":
    asyncio.run(main())
