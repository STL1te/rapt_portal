r"""Build a corpus of recipes with an explicit BrewZilla device paragraph appended.

The source corpora state no device settings at all: across 11 125 RU recipes, PID is
mentioned zero times, heating power 22 times, alerts 4 times. So `heat_power_pct`,
`rest_power_pct` and `mash_pid_enabled` cannot be distilled out of them - v3/v4/v5 carry
1, 0 and 0 examples respectively. This writes a corpus where the device settings ARE
stated, so the teacher has something to extract into brewzilla_overrides.

Output is a plain corpus file in the input's own format: feed it to
evaluate_recipe_wizard.py like any other corpus. A sidecar records what was injected
into each recipe, which is the ground truth for the acceptance gate (--check).

Pick a slice that does NOT overlap the plain distillation run: build_sft_dataset groups
examples by (corpus file name, index), so an augmented recipe lands in a different group
than its original and split_by_recipe may put one in train and the other in test - same
recipe body, leaked. With the same --shuffle seed, --offset past the plain run's --count
guarantees disjoint recipes.

Usage (from backend/):
  uv run python scripts\\augment_device_text.py CORPUS OUT_CORPUS SIDECAR ^
    --shuffle 42 --offset 3000 --count 400
  uv run python scripts\\augment_device_text.py --check RESULTS SIDECAR
  uv run python scripts\\augment_device_text.py --selftest
"""

import argparse
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.evaluate_recipe_wizard import _is_grain, _load_results, _source

# A rest reads as "63°C - 30 мин" / "63 С 30мин" / "152F 30 min" in these corpora.
_REST_RU = re.compile(r"\d{2}\s?°?\s?[CСc]\D{0,4}\d{1,3}\s?м", re.IGNORECASE)
_REST_EN = re.compile(r"\d{2,3}\s?°?\s?[FC]\D{0,6}\d{1,3}\s?min", re.IGNORECASE)

# Each component is chosen independently, so the model learns partial filling instead of
# an all-or-nothing package. {v} is the stated value.
_PHRASES: dict[str, dict[str, list[str]]] = {
    "heat_power_pct": {
        "ru": [
            "Нагрев автоматический на {v}% мощности.",
            "Разогрев до каждой паузы вести на {v}% мощности.",
            "Мощность нагрева {v}%.",
            "Выход на температуру — {v}% мощности ТЭНа.",
            "Нагревать на {v} процентах мощности.",
        ],
        "en": [
            "Heat to each step at {v}% power.",
            "Heating power {v}%.",
            "Ramp up at {v}% element power.",
            "Use {v}% power when heating.",
        ],
    },
    "rest_power_pct": {
        "ru": [
            "Поддержание пауз на {v}% мощности.",
            "Во время пауз держать {v}% мощности.",
            "Удержание температуры паузы — {v}%.",
            "На паузах мощность {v}%.",
            "Паузы выдерживать на {v} процентах.",
        ],
        "en": [
            "Hold each rest at {v}% power.",
            "Rest power {v}%.",
            "Maintain rests at {v}% element power.",
            "Keep {v}% power during the rests.",
        ],
    },
    "mash_pid_enabled": {
        "ru": [
            "Удержание пауз с ПИД-регулированием.",
            "Паузы держать с ПИД.",
            "Включить ПИД-регулятор на паузах затирания.",
            "Температуру пауз стабилизировать ПИД-регулированием.",
        ],
        "en": [
            "Hold the rests with PID control.",
            "Enable PID during the mash rests.",
            "Use the PID regulator for rest temperatures.",
        ],
    },
    "mash_pid_disabled": {
        "ru": [
            "ПИД-регулирование на паузах не использовать.",
            "Паузы держать без ПИД.",
            "ПИД отключить.",
        ],
        "en": [
            "Do not use PID on the rests.",
            "Keep PID off during the mash.",
        ],
    },
    "rest_end_alerts": {
        "ru": [
            "Предупреждение в конце каждой паузы.",
            "Сигналить об окончании каждой паузы.",
            "В конце каждой паузы — уведомление.",
            "Оповещать о завершении каждой паузы затирания.",
        ],
        "en": [
            "Alert at the end of every rest.",
            "Notify when each mash rest finishes.",
            "Sound an alert at the end of each mash step.",
        ],
    },
    "sparge_alert_text": {
        "ru": [
            "Отдельное предупреждение на промывку.",
            "Уведомить, когда пора на промывку.",
            "Сигнал перед промывкой дробины.",
        ],
        "en": [
            "Alert when it is time to sparge.",
            "Separate notification before sparging.",
        ],
    },
    "mash_in_alert_text": {
        "ru": [
            "Предупреждение на засыпку солода.",
            "Сигнал, когда пора засыпать солод.",
        ],
        "en": [
            "Alert when it is time to add the grain.",
            "Notify at grain-in.",
        ],
    },
}

_HEAT_VALUES = (70, 75, 80, 85, 90, 95, 100)
_REST_VALUES = (30, 35, 40, 45, 50, 55, 60)
# Probability each optional component appears. Powers dominate: they are the fields with
# 1 and 0 training examples, and the ramp steps depend on BOTH being present.
_INCLUSION = {
    "heat_power_pct": 0.85,
    "rest_power_pct": 0.80,
    "pid": 0.70,
    "rest_end_alerts": 0.55,
    "sparge_alert_text": 0.30,
    "mash_in_alert_text": 0.25,
}


def _rest_count(text: str, lang: str) -> int:
    return len((_REST_RU if lang == "ru" else _REST_EN).findall(text))


def build_paragraph(rng: random.Random, lang: str) -> tuple[str, dict]:
    """One device paragraph plus the overrides a correct extraction must produce."""
    parts: list[str] = []
    expected: dict = {}

    def pick(component: str, **fmt) -> str:
        return rng.choice(_PHRASES[component][lang]).format(**fmt)

    if rng.random() < _INCLUSION["heat_power_pct"]:
        value = rng.choice(_HEAT_VALUES)
        expected["heat_power_pct"] = float(value)
        parts.append(pick("heat_power_pct", v=value))
    if rng.random() < _INCLUSION["rest_power_pct"]:
        # Equal powers 10% of the time: the compiler emits no ramp step then, and the
        # model must not learn that a rest power is always lower than the heat power.
        heat = expected.get("heat_power_pct")
        if heat is not None and rng.random() < 0.10:
            value = int(heat)
        else:
            value = rng.choice([v for v in _REST_VALUES if heat is None or v < heat] or [30])
        expected["rest_power_pct"] = float(value)
        parts.append(pick("rest_power_pct", v=value))
    if rng.random() < _INCLUSION["pid"]:
        enabled = rng.random() < 0.75
        expected["mash_pid_enabled"] = enabled
        parts.append(pick("mash_pid_enabled" if enabled else "mash_pid_disabled"))
    if rng.random() < _INCLUSION["rest_end_alerts"]:
        expected["rest_end_alerts"] = "nonempty"
        parts.append(pick("rest_end_alerts"))
    if rng.random() < _INCLUSION["sparge_alert_text"]:
        expected["sparge_alert_text"] = "nonempty"
        parts.append(pick("sparge_alert_text"))
    if rng.random() < _INCLUSION["mash_in_alert_text"]:
        expected["mash_in_alert_text"] = "nonempty"
        parts.append(pick("mash_in_alert_text"))

    if not parts:  # never emit a recipe that teaches nothing
        value = rng.choice(_HEAT_VALUES)
        expected["heat_power_pct"] = float(value)
        parts.append(pick("heat_power_pct", v=value))

    rng.shuffle(parts)
    return " ".join(parts), expected


def _augment_row(row: dict, paragraph: str) -> dict:
    """Append the paragraph where _source() will pick it up, per corpus format."""
    augmented = dict(row)
    if "BrewMethod" in row:  # Brewer's Friend: _source_en emits `notes` last
        augmented["notes"] = f"{row.get('notes') or ''}\n{paragraph}".strip()
    else:
        augmented["full_description"] = f"{row['full_description'].rstrip()}\n{paragraph}"
    return augmented


def generate(args: argparse.Namespace) -> None:
    rows = [
        json.loads(line)
        for line in args.corpus.read_text(encoding="utf-8").split("\n")
        if line.strip()
    ]
    lang = "en" if rows and "BrewMethod" in rows[0] else "ru"
    # Same ordering as evaluate_recipe_wizard._select, so --offset past the plain run's
    # --count yields recipes that run never touched.
    pairs = [(index, row) for index, row in enumerate(rows) if _is_grain(row)]
    if args.shuffle is not None:
        random.Random(args.shuffle).shuffle(pairs)

    rng = random.Random(args.seed)
    selected, skipped = [], 0
    for index, row in pairs[args.offset:]:
        if len(selected) >= args.count:
            break
        if _rest_count(_source(row), lang) < args.min_rests:
            skipped += 1
            continue
        selected.append((index, row))

    out_rows, sidecar = [], []
    for index, row in selected:
        paragraph, expected = build_paragraph(rng, lang)
        out_rows.append(_augment_row(row, paragraph))
        sidecar.append({
            "out_index": len(out_rows) - 1,  # index inside OUT_CORPUS, what the runner keys on
            "source_index": index,
            "name": row.get("name", row.get("Name")),
            "paragraph": paragraph,
            "expected": expected,
        })

    args.out_corpus.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in out_rows),
        encoding="utf-8",
    )
    args.sidecar.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in sidecar),
        encoding="utf-8",
    )
    counts: dict[str, int] = {}
    for entry in sidecar:
        for field in entry["expected"]:
            counts[field] = counts.get(field, 0) + 1
    print(f"{len(out_rows)} recipes written ({skipped} skipped: fewer than "
          f"{args.min_rests} rests), lang={lang}")
    for field, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {field:24} {count:5} ({count / max(len(out_rows), 1):.0%})")


def check(args: argparse.Namespace) -> None:
    """Acceptance gate: did the teacher fill exactly the fields the text states?"""
    results = _load_results(args.results)
    sidecar = {
        entry["out_index"]: entry
        for line in args.sidecar.read_text(encoding="utf-8").split("\n")
        if line.strip()
        for entry in [json.loads(line)]
    }
    per_field: dict[str, list[int]] = {}
    perfect = scored = 0
    misses: list[str] = []
    for index, entry in sorted(sidecar.items()):
        result = results.get(index)
        if not result or not result.get("spec"):
            continue
        scored += 1
        overrides = result["spec"].get("brewzilla_overrides") or {}
        row_ok = True
        for field, want in entry["expected"].items():
            got = overrides.get(field)
            ok = bool(got) if want == "nonempty" else got == want
            per_field.setdefault(field, [0, 0])
            per_field[field][1] += 1
            per_field[field][0] += ok
            if not ok:
                row_ok = False
                if len(misses) < 15:
                    misses.append(
                        f"  index={index} {field}: want {want!r}, got {got!r}"
                    )
        perfect += row_ok
    if not scored:
        raise SystemExit("no scored rows: results and sidecar do not overlap")
    print(f"scored {scored} recipes, all stated fields correct in {perfect} "
          f"({perfect / scored:.0%}) — gate is 95%")
    for field, (hits, total) in sorted(per_field.items(), key=lambda kv: -kv[1][1]):
        print(f"  {field:24} {hits:5}/{total:<5} {hits / total:5.0%}")
    if misses:
        print("misses:")
        print("\n".join(misses))


def selftest() -> None:
    """Every stated number must survive into `expected`, or the gate scores noise."""
    rng = random.Random(0)
    for lang in ("ru", "en"):
        for _ in range(500):
            paragraph, expected = build_paragraph(rng, lang)
            assert paragraph.strip(), "empty paragraph"
            assert expected, "paragraph teaches nothing"
            for field in ("heat_power_pct", "rest_power_pct"):
                if field in expected:
                    stated = f"{int(expected[field])}"
                    assert stated in paragraph, f"{field}={stated} missing from {paragraph!r}"
            if expected.get("mash_pid_enabled") is False:
                assert re.search(r"не использовать|без ПИД|отключить|not use|off",
                                 paragraph), paragraph
            heat, rest = expected.get("heat_power_pct"), expected.get("rest_power_pct")
            if heat is not None and rest is not None:
                assert rest <= heat, f"rest {rest} above heat {heat}"
    # A row must carry the paragraph into what the teacher actually reads.
    row = {"name": "x", "style_full": "s", "type": "Зерновой", "volume": "20",
           "full_description": "Паузы: 63°C - 30 мин"}
    assert "МАРКЕР" in _source(_augment_row(row, "МАРКЕР"))
    print("selftest ok")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("corpus", type=Path, nargs="?")
    parser.add_argument("out_corpus", type=Path, nargs="?")
    parser.add_argument("sidecar", type=Path, nargs="?")
    parser.add_argument("--shuffle", type=int, metavar="SEED",
                        help="same seed as the plain distillation run")
    parser.add_argument("--offset", type=int, default=0,
                        help="skip this many selected recipes: set it to the plain run's "
                             "--count so the two never share a recipe")
    parser.add_argument("--count", type=int, default=400)
    parser.add_argument("--min-rests", type=int, default=3)
    parser.add_argument("--seed", type=int, default=7, help="device paragraph randomness")
    parser.add_argument("--check", nargs=2, metavar=("RESULTS", "SIDECAR"), type=Path)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()

    if args.selftest:
        return selftest()
    if args.check:
        args.results, args.sidecar = args.check
        return check(args)
    if not (args.corpus and args.out_corpus and args.sidecar):
        parser.error("CORPUS OUT_CORPUS SIDECAR are required unless --check/--selftest")
    generate(args)


if __name__ == "__main__":
    main()
