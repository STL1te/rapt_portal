"""Split-hygiene checks for the SFT dataset builder."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_sft_dataset import split_by_recipe


def _entries(recipes: int, variants: int) -> list[tuple[tuple[str, int], str, dict]]:
    """`variants` examples per recipe, all carrying that recipe's single target."""
    return [
        (("corpus.jsonl", recipe), f"spec-{recipe}", {"target": f"spec-{recipe}", "v": v})
        for recipe in range(recipes)
        for v in range(variants)
    ]


def test_split_by_recipe_keeps_every_variant_on_one_side():
    entries = _entries(recipes=50, variants=3)
    val, test, train = split_by_recipe(entries, val_count=15, test_count=15, seed=0)

    assert len(val) + len(test) + len(train) == len(entries)
    train_targets = {example["target"] for example in train}
    for held_out in (val, test):
        assert train_targets.isdisjoint({example["target"] for example in held_out})
    # Whole recipes only: 3 variants each, so a split never stops mid-recipe.
    assert len(val) % 3 == 0 and len(test) % 3 == 0


def test_split_by_recipe_is_deterministic_for_a_seed():
    entries = _entries(recipes=20, variants=2)
    assert split_by_recipe(entries, 6, 6, seed=7) == split_by_recipe(entries, 6, 6, seed=7)


def test_split_by_recipe_without_holdout_keeps_everything_in_train():
    entries = _entries(recipes=5, variants=2)
    val, test, train = split_by_recipe(entries, 0, 0, seed=0)

    assert (val, test) == ([], [])
    assert len(train) == len(entries)
