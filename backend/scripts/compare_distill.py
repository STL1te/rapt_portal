"""Compare two distillation runs (different teachers) on their shared corpus indices.

Reports per-run status counts and, over rows both runs extracted, leaf agreement of
the candidate spec against the reference spec (same metric as eval_sft_test.py, so
teacher-vs-teacher and student-vs-teacher numbers are on one scale). Neither teacher
is ground truth: disagreement localizes where the runs differ, it does not rank them.

Usage (from backend/):
  uv run python scripts\\compare_distill.py <reference.jsonl> <candidate.jsonl>
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.eval_sft_test import _leaf_match


def _rows(path: Path) -> dict[int, dict]:
    return {
        row["index"]: row
        for line in path.read_text(encoding="utf-8").split("\n")
        if line.strip()
        for row in [json.loads(line)]
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--worst", type=int, default=5, help="show N lowest-agreement rows")
    args = parser.parse_args()

    reference, candidate = _rows(args.reference), _rows(args.candidate)
    shared = sorted(set(reference) & set(candidate))
    print(f"shared indices: {len(shared)} (ref {len(reference)}, cand {len(candidate)})")
    for label, rows in (("reference", reference), ("candidate", candidate)):
        counts: dict[str, int] = {}
        for index in shared:
            status = rows[index]["status"]
            counts[status] = counts.get(status, 0) + 1
        print(f"{label:10s} {json.dumps(counts, sort_keys=True, separators=(',', ':'))}")

    scored, worst = [], {}
    for index in shared:
        if "spec" not in reference[index] or "spec" not in candidate[index]:
            continue
        matched, total, mismatches = _leaf_match(reference[index]["spec"], candidate[index]["spec"])
        scored.append((matched / total, index, mismatches))
        for path in mismatches:
            key = path.split("[")[0]  # collapse list indices: hop[3].amount -> hop.amount
            worst[key] = worst.get(key, 0) + 1
    if not scored:
        return
    scored.sort()
    rates = [rate for rate, _, _ in scored]
    print(
        f"\nleaf agreement over {len(scored)} rows: median {rates[len(rates) // 2]:.0%}, "
        f"p10 {rates[int(len(rates) * 0.1)]:.0%}, min {rates[0]:.0%}"
    )
    print("top diverging paths:")
    for path, count in sorted(worst.items(), key=lambda item: -item[1])[:15]:
        print(f"  {count:3d}  {path}")
    print("lowest-agreement rows:")
    for rate, index, mismatches in scored[: args.worst]:
        print(f"  index={index} {rate:.0%}  {', '.join(mismatches[:6])}")


if __name__ == "__main__":
    main()
