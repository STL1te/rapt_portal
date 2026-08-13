r"""Drop `culture_additions[*].amount` from distillation specs where the source states no
yeast quantity at all.

BeerJSON marks the field required (in an allOf branch), so our model used to demand it
too — forcing the teacher to invent "1 pkg" for every recipe that names a yeast without a
quantity (892 RU + 3308 EN rows). The field is optional now, with a placeholder added only
at BeerJSON export, so these stored amounts are simply wrong and the correct value is
absent. The condition is mechanically decidable, so this is a local edit rather than a
re-distillation: no LLM call, and no risk of re-rolling unrelated fields.

Conservative on purpose — an amount is dropped only when ALL hold:
  * its unit is a counted one (pkg/unit/each/...), i.e. the "assumed one sachet" shape;
  * no number followed by a quantity unit appears anywhere near the yeast mentions or the
    culture's own name in the source.
A stated mass ("Дрожжи: US-05 11 грамм") therefore stays, and so does anything ambiguous.

Usage (from backend/):
  uv run python scripts\strip_invented_culture_amounts.py RESULTS CORPUS [--apply]
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parents[1]))

from features.ai.recipe_wizard import SubmitRecipe  # noqa: E402

_READY = ("ok", "ok_repaired")
_COUNTED = {"1", "unit", "each", "dimensionless", "pkg"}
_YEAST = re.compile(
    r"дрожж|yeast|wyeast|safale|saflager|сафэль|сафбрю|fermentis|lallemand|mangrove|"
    r"lalvin|wlp|omega|imperial|nottingham|kveik|us-?05|s-?04|ferment with",
    re.I,
)
_QTY = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:гр|г\b|грамм|кг\b|мл\b|л\b|пак|шт|уп|"
    r"g\b|gram|kg\b|ml\b|oz\b|lb\b|pack|packet|sachet|pkg|vial|smack)",
    re.I,
)


def _source_text(row: dict) -> str:
    if "BrewMethod" in row:  # Brewer's Friend: yeast lives in instructions/notes
        parts = [row.get("Name") or ""]
        parts += [str(x) for x in row.get("ingredients") or []]
        parts += [str(p) for p in row.get("instructions") or [] if p]
        parts.append(str(row.get("notes") or ""))
        return "\n".join(parts)
    return f"{row.get('name', '')}\n{row.get('full_description') or ''}"


def _quantity_context(source: str, names: list[str]) -> str:
    """The lines that mention a yeast, where a stated yeast quantity would have to appear.

    Whole lines, not a character window: both corpora are line-oriented (one ingredient
    per line in Brewer's Friend, "36 гр | Каскад | Внесение в котел" per line in the RU
    export), so a window bleeds into the neighbouring ingredient and reads its weight as
    the yeast's. Splitting on "|" instead would be worse — in the RU export the quantity
    is its own "|" field, so the amount would be severed from the name it belongs to.
    """
    lowered = [name.lower() for name in names if len(name) >= 3]
    return " || ".join(
        line
        for line in source.splitlines()
        if _YEAST.search(line) or any(name in line.lower() for name in lowered)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--apply", action="store_true", help="write the file back")
    parser.add_argument("--samples", type=int, default=8)
    args = parser.parse_args()

    rows = [
        json.loads(line)
        for line in args.corpus.read_text(encoding="utf-8").split("\n")
        if line.strip()
    ]
    records = [
        json.loads(line)
        for line in args.results.read_text(encoding="utf-8").split("\n")
        if line.strip()
    ]

    stripped = kept_mass = kept_stated = touched_rows = 0
    samples: list[str] = []
    for record in records:
        if record.get("status") not in _READY:
            continue
        cultures = (((record.get("spec") or {}).get("recipe") or {}).get("ingredients") or {}).get(
            "culture_additions"
        ) or []
        if not cultures:
            continue
        source = _source_text(rows[record["index"]])
        context = _quantity_context(source, [c.get("name") or "" for c in cultures])
        has_quantity = bool(_QTY.search(context))
        changed = False
        for culture in cultures:
            amount = culture.get("amount")
            if not amount:
                continue
            if amount["unit"] not in _COUNTED:
                kept_mass += 1
                continue
            if has_quantity:
                kept_stated += 1
                continue
            if len(samples) < args.samples:
                snippet = re.sub(r"\s+", " ", context[:110])
                samples.append(
                    f"  idx {record['index']}: {culture.get('name')!r} "
                    f"{amount['value']:g} {amount['unit']} -> absent | ctx: {snippet!r}"
                )
            del culture["amount"]
            stripped += 1
            changed = True
        if changed:
            touched_rows += 1
            SubmitRecipe.model_validate(record["spec"])  # must still validate

    print(
        f"{args.results.name}: stripped={stripped} in {touched_rows} rows | "
        f"kept because mass/volume={kept_mass}, kept because quantity stated={kept_stated}"
    )
    for line in samples:
        print(line)
    if args.apply:
        args.results.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
        )
        print(f"WROTE {args.results}")
    else:
        print("dry run — pass --apply to write")


if __name__ == "__main__":
    main()
