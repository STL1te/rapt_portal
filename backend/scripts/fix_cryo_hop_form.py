r"""Set `hop_additions[*].form` to "powder" for cryo/lupulin hops in stored specs.

BeerJSON's form enum is exactly extract/leaf/leaf (wet)/pellet/powder/plug — there is no
"cryo". Cryo hops (LupuLN2, LupoMax, "Симкое Крио") are concentrated lupulin powder, so
"powder" is the right token; the teacher used to record them as "pellet", and one prompt
attempt to emit "cryo" outright failed schema validation. The prompt now says so, and this
backfills the rows distilled before it did.

Only `form` changes: the variety name keeps its Cryo/LupuLN2 wording, which is what the
source states.

Usage (from backend/):
  uv run python scripts\fix_cryo_hop_form.py RESULTS [RESULTS ...] [--apply]
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from features.ai.recipe_wizard import SubmitRecipe  # noqa: E402

_READY = ("ok", "ok_repaired")
_CRYO = re.compile(r"\bcryo\b|cryo-?hop|lupuln|lupomax|крио|лупулин", re.I)
_POWDER = "powder"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path, nargs="+")
    parser.add_argument("--apply", action="store_true", help="write the files back")
    parser.add_argument("--samples", type=int, default=5)
    args = parser.parse_args()

    for path in args.results:
        records = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").split("\n")
            if line.strip()
        ]
        changed = already = rows = 0
        samples: list[str] = []
        for record in records:
            if record.get("status") not in _READY:
                continue
            hops = (((record.get("spec") or {}).get("recipe") or {}).get("ingredients") or {}).get(
                "hop_additions"
            ) or []
            touched = False
            for hop in hops:
                if not _CRYO.search(hop.get("name") or ""):
                    continue
                if hop.get("form") == _POWDER:
                    already += 1
                    continue
                if len(samples) < args.samples:
                    samples.append(
                        f"  idx {record['index']}: {hop.get('name')!r} "
                        f"{hop.get('form')!r} -> {_POWDER!r}"
                    )
                hop["form"] = _POWDER
                changed += 1
                touched = True
            if touched:
                rows += 1
                SubmitRecipe.model_validate(record["spec"])  # must still validate
        print(f"{path.name}: {changed} hop forms in {rows} rows (already powder: {already})")
        for line in samples:
            print(line)
        if args.apply and changed:
            path.write_text(
                "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
                encoding="utf-8",
            )
            print(f"  WROTE {path}")
    if not args.apply:
        print("dry run — pass --apply to write")


if __name__ == "__main__":
    main()
