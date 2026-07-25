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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))  # features.* when PYTHONPATH is unset

from pydantic import ValidationError

from evaluate_recipe_wizard import _READY, _load_results, _source
from features.ai.recipe_wizard import SubmitRecipe

DEFAULT_SYSTEM = Path(__file__).parents[1] / "features" / "ai" / "prompts" / "recipe_wizard.md"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "pairs", type=Path, nargs="+", metavar="RESULTS CORPUS",
        help="alternating results.jsonl / corpus.jsonl paths",
    )
    parser.add_argument("--system", type=Path, default=DEFAULT_SYSTEM,
                        help="system prompt file fed during distillation")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--val-fraction", type=float, default=0.05)
    parser.add_argument("--test-fraction", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    if len(args.pairs) % 2:
        parser.error("pairs must be alternating RESULTS CORPUS paths (even count)")

    system_prompt = args.system.read_text(encoding="utf-8").strip()
    examples = []
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
                SubmitRecipe.model_validate(spec)
            except ValidationError as error:
                invalid += 1
                print(f"skip index {index} ({result['name']}): stale spec: {error.errors()[0]}")
                continue
            examples.append({
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": _source(row).strip()},
                    {
                        "role": "assistant",
                        "content": json.dumps(spec, ensure_ascii=False, separators=(",", ":")),
                    },
                ]
            })
            ready += 1
        print(f"{results_path.name}: {ready} examples, {invalid} stale-schema skips")

    lengths = sorted(sum(len(m["content"]) for m in ex["messages"]) for ex in examples)
    print(
        f"chars/example: median {lengths[len(lengths) // 2]}, "
        f"p95 {lengths[int(len(lengths) * 0.95)]}, max {lengths[-1]}"
    )

    random.Random(args.seed).shuffle(examples)
    val_count = round(len(examples) * args.val_fraction)
    test_count = round(len(examples) * args.test_fraction)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, subset in (
        ("val.jsonl", examples[:val_count]),
        ("test.jsonl", examples[val_count:val_count + test_count]),
        ("train.jsonl", examples[val_count + test_count:]),
    ):
        path = args.output_dir / name
        path.write_text(
            "".join(json.dumps(example, ensure_ascii=False) + "\n" for example in subset),
            encoding="utf-8",
        )
        print(f"{path}: {len(subset)} examples")


if __name__ == "__main__":
    main()
