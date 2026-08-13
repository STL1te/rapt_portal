"""Build a chat-format SFT dataset (Gemma QLoRA) from recipe-wizard distillation results.

Each example replays exactly what the teacher model saw: system = the distillation
system prompt, user = the source text rebuilt from the corpus row via _source(),
assistant = the accepted `spec` JSON. ok_repaired rows become clean single-turn pairs
(the correction turn is dropped). Gemma has no system role: trainers (TRL/unsloth)
fold it into the first user turn via the chat template.

Usage (from backend/, same as run_distillation.cmd):
  uv run python scripts\\build_sft_dataset.py ^
    D:\\Work\\projects\\beer_knowledge\\data\\distil\\distill.jsonl D:\\Work\\projects\\beer_knowledge\\data\\recipes_detail.jsonl ^
    D:\\Work\\projects\\beer_knowledge\\data\\distil\\distill_en.jsonl D:\\Work\\projects\\beer_knowledge\\data\\beersfriend_detail.jsonl ^
    --system D:\\Work\\projects\\beer_knowledge\\data\\distil\\recipe_wizard_system.md ^
    --output-dir D:\\Work\\projects\\beer_knowledge\\data\\sft
"""

import argparse
import json
import random
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))  # features.* when PYTHONPATH is unset

from evaluate_recipe_wizard import _READY, _load_results, _source
from pydantic import ValidationError

from features.ai.recipe_wizard import SubmitRecipe

DEFAULT_SYSTEM = Path(__file__).parents[1] / "prompts" / "recipe_wizard.md"


def split_by_recipe(
    entries: list[tuple[tuple[str, int], str, dict]],
    val_count: int,
    test_count: int,
    seed: int,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Carve val/test out in whole recipes. One recipe yields several examples - the
    distillation row, its freeform rewrite, its partial cuts - and they all share a
    target, so splitting inside a recipe would put a memorised answer in val/test and
    inflate the score. Splits therefore land near the requested size, not exactly on it.
    """
    groups: dict[tuple[str, int], list[dict]] = {}
    for group, _, example in entries:
        groups.setdefault(group, []).append(example)
    order = list(groups)
    random.Random(seed).shuffle(order)

    def carve(count: int) -> list[dict]:
        subset: list[dict] = []
        while order and len(subset) < count:
            subset.extend(groups[order.pop()])
        return subset

    val, test = carve(val_count), carve(test_count)
    return val, test, [example for group in order for example in groups[group]]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "pairs",
        type=Path,
        nargs="+",
        metavar="RESULTS CORPUS",
        help="alternating results.jsonl / corpus.jsonl paths",
    )
    parser.add_argument(
        "--system",
        type=Path,
        default=DEFAULT_SYSTEM,
        help="system prompt file fed during distillation",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--val-fraction", type=float, default=0.05)
    parser.add_argument("--test-fraction", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--frozen",
        type=Path,
        nargs="*",
        default=[],
        help="existing split files (val/test) kept verbatim: their examples are excluded "
        "from train by spec match and the files are copied into --output-dir, so "
        "metrics stay comparable across model iterations",
    )
    args = parser.parse_args()
    if len(args.pairs) % 2:
        parser.error("pairs must be alternating RESULTS CORPUS paths (even count)")

    system_prompt = args.system.read_text(encoding="utf-8").strip()
    frozen_rows = [
        json.loads(line)
        for path in args.frozen
        for line in path.read_text(encoding="utf-8").split("\n")
        if line.strip()
    ]
    frozen_specs = {row["messages"][-1]["content"] for row in frozen_rows}
    # Also key on the USER turn: a held-out recipe is identified by its source text, which
    # never changes, whereas the target does the moment an extraction rule is fixed. Spec
    # matching alone silently under-matched (65 of 88 after the whirlpool + culture-amount
    # corrections), which would have leaked 23 test recipes into train.
    frozen_sources = {row["messages"][1]["content"].strip() for row in frozen_rows}
    frozen_hits = 0
    # (recipe key, spec as recorded, example). One recipe yields several examples -
    # the distillation row, its freeform rewrite, its partial cuts - all sharing a
    # target, so they must never straddle a split boundary.
    entries: list[tuple[tuple[str, int], str, dict]] = []
    for results_path, corpus_path in zip(args.pairs[::2], args.pairs[1::2]):
        rows = [
            json.loads(line)
            for line in corpus_path.read_text(encoding="utf-8").split("\n")
            if line.strip()
        ]
        ready = invalid = 0
        for index, result in sorted(_load_results(results_path).items()):
            if result["status"] not in _READY:
                continue
            row = rows[index]
            corpus_name = row.get("name", row.get("Name"))
            if corpus_name != result["name"]:
                raise SystemExit(
                    f"{results_path} index {index} is {result['name']!r} but "
                    f"{corpus_path} has {corpus_name!r}: wrong corpus for these results"
                )
            spec = result["spec"]
            # Recorded specs were dumped with exclude_none, dropping the explicit
            # top-level null the prompt skeleton mandates; restore it.
            spec.setdefault("brewzilla_overrides", None)
            try:
                submit = SubmitRecipe.model_validate(spec)
            except ValidationError as error:
                invalid += 1
                print(f"skip index {index} ({result['name']}): stale spec: {error.errors()[0]}")
                continue
            # Frozen files carry the old omit-style dumps; match on that form.
            compact = json.dumps(spec, ensure_ascii=False, separators=(",", ":"))
            # Target keeps every key with explicit nulls — the same shape the strict
            # response_format grammar forces at inference, so the student learns
            # "no value" = null instead of inventing ""/0 for forced keys.
            target = json.dumps(
                submit.model_dump(mode="json", by_alias=True),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            entries.append(
                (
                    (corpus_path.name, index),
                    compact,
                    {
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            # freeform_rewrite.py rows carry the hand-typed rewrite as the
                            # user turn; plain distillation rows rebuild it from the corpus
                            {
                                "role": "user",
                                "content": (result.get("rewrite") or _source(row)).strip(),
                            },
                            {"role": "assistant", "content": target},
                        ]
                    },
                )
            )
            ready += 1
        print(f"{results_path.name}: {ready} examples, {invalid} stale-schema skips")

    # A recipe held out in a frozen split is out of the dataset entirely: its freeform
    # rewrite carries the very same target, so keeping the sibling would put the
    # answer in train. Matching a frozen row identifies the recipe, then the whole
    # group goes - not just the row that matched.
    frozen_groups = {
        group
        for group, compact, example in entries
        if compact in frozen_specs or example["messages"][1]["content"] in frozen_sources
    }
    if frozen_groups:
        kept = [entry for entry in entries if entry[0] not in frozen_groups]
        frozen_hits = len(entries) - len(kept)
        entries = kept

    lengths = sorted(sum(len(m["content"]) for m in ex["messages"]) for _, _, ex in entries)
    print(
        f"chars/example: median {lengths[len(lengths) // 2]}, "
        f"p95 {lengths[int(len(lengths) * 0.95)]}, max {lengths[-1]}"
    )

    print(f"{len(entries)} examples from {len({group for group, _, _ in entries})} recipes")

    # A frozen file replaces fresh carving for its split only: freezing just
    # test.jsonl keeps the cross-iteration comparison point while val is carved
    # fresh from the current mix (so it tracks freeform/partial examples too).
    frozen_names = {path.name for path in args.frozen}
    val_count = 0 if "val.jsonl" in frozen_names else round(len(entries) * args.val_fraction)
    test_count = 0 if "test.jsonl" in frozen_names else round(len(entries) * args.test_fraction)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    val, test, train = split_by_recipe(entries, val_count, test_count, args.seed)
    for name, subset in (("val.jsonl", val), ("test.jsonl", test), ("train.jsonl", train)):
        path = args.output_dir / name
        if name in frozen_names:
            continue
        path.write_text(
            "".join(json.dumps(example, ensure_ascii=False) + "\n" for example in subset),
            encoding="utf-8",
        )
        print(f"{path}: {len(subset)} examples")
    if args.frozen:
        print(
            f"frozen: {len(frozen_groups)} recipes matched, "
            f"{frozen_hits} examples excluded (matches plus their siblings)"
        )
        for source_path in args.frozen:
            shutil.copyfile(source_path, args.output_dir / source_path.name)
            print(f"{args.output_dir / source_path.name}: copied verbatim")


if __name__ == "__main__":
    main()
