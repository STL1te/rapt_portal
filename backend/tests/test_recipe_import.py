"""Tests for the recipe import facade: BrewFather JSON / BeerXML / BeerJSON ->
RecipeModel, compiled through the same compile_brewzilla_profile the AI wizard uses."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from features.recipes.beerjson import parse_beerjson
from features.recipes.beerjson_models import to_beerjson_document
from features.recipes.beerxml import parse_beerxml
from features.recipes.brewfather import parse_brewfather_json
from features.recipes.brewzilla_compiler import compile_brewzilla_profile
from features.recipes.importers import import_recipe

DATA_DIR = Path(__file__).parent / "data"

JSON_FIXTURES = sorted(DATA_DIR.glob("*.json"))
XML_FIXTURES = sorted(DATA_DIR.glob("*.xml"))
WHEAT_ALE_JSON = DATA_DIR / "Brewfather_RECIPE_AmericanWheatAle_20260828.json"


def _step(profile, name):
    return next(step for step in profile["steps"] if step["name"] == name)


def _load_brewfather(path: Path):
    return parse_brewfather_json(json.loads(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("path", JSON_FIXTURES, ids=lambda p: p.name)
def test_parses_and_compiles_brewfather_json_fixtures(path):
    recipe = _load_brewfather(path)
    assert recipe.name
    assert recipe.mash and len(recipe.mash.mash_steps) >= 1
    assert recipe.ingredients.hop_additions
    profile = compile_brewzilla_profile(recipe)
    assert profile["name"] == recipe.name
    assert len(profile["steps"]) >= 4  # Mash In, >=1 rest, Boil, Cooling


@pytest.mark.parametrize("path", XML_FIXTURES, ids=lambda p: p.name)
def test_parses_and_compiles_beerxml_fixtures(path):
    recipe = parse_beerxml(path.read_text(encoding="iso-8859-1"))
    assert recipe.name
    assert recipe.mash and len(recipe.mash.mash_steps) >= 1
    assert recipe.ingredients.hop_additions
    profile = compile_brewzilla_profile(recipe)
    assert profile["name"] == recipe.name
    assert len(profile["steps"]) >= 4


def test_wheat_ale_recipe_gets_a_whirlpool_step():
    # American Wheat Ale fixtures carry "Aroma" hops -> a whirlpool boil step.
    profile = compile_brewzilla_profile(_load_brewfather(WHEAT_ALE_JSON))
    assert "Whirlpool" in [s["name"] for s in profile["steps"]]


def test_keeps_hop_additions_the_source_left_unnamed():
    """Regression: the Corona Extra export has a second boil hop with name=null.
    An unnamed row still carries an amount and a timing, so it must survive import
    (and produce its boil alert) instead of being silently dropped."""
    path = DATA_DIR / "Brewfather_RECIPE_CoronaExtra_20260828.json"
    recipe = _load_brewfather(path)

    hops = recipe.ingredients.hop_additions
    assert len(hops) == 2, "the unnamed second hop addition was dropped"
    assert hops[1].name == "Hop"
    assert hops[1].amount.value == 10
    assert hops[1].timing.duration.value == 15

    boil_alerts = _step(compile_brewzilla_profile(recipe), "Boil")["alerts"]
    # 75 min boil: 60 min hop fires at 15 min, 15 min hop at 60 min
    assert [(a["alertText"], a["length"]) for a in boil_alerts] == [
        ("35 g Hallertauer Mittelfrueh", 900),
        ("10 g Hop", 3600),
    ]


def test_whirlpool_temperature_agrees_between_json_and_beerxml_exports():
    """BeerXML 1.0 cannot state a hopstand temperature — Brewfather leaves HOP_TEMP
    empty while its JSON export carries the stand. Without a default the compiler would
    fall back to the boil temperature and stand the aroma hops at 100 °C, so the two
    exports of one recipe would disagree."""
    json_recipe = _load_brewfather(DATA_DIR / "Brewfather_RECIPE__20260828.json")
    xml_recipe = parse_beerxml(
        (DATA_DIR / "Brewfather_BeerXML__20260828.xml").read_text(encoding="iso-8859-1")
    )

    def whirlpool(profile):
        step = _step(profile, "Whirlpool")
        return step["temperature"], step["length"]

    assert whirlpool(compile_brewzilla_profile(json_recipe)) == (80.0, 1200)
    assert whirlpool(compile_brewzilla_profile(xml_recipe)) == (80.0, 1200)


def test_whirlpool_temperature_from_the_file_beats_the_default():
    xml = (DATA_DIR / "Brewfather_BeerXML__20260828.xml").read_text(encoding="iso-8859-1")
    filled = xml.replace("<HOP_TEMP/>", "<HOP_TEMP>75</HOP_TEMP>")

    profile = compile_brewzilla_profile(parse_beerxml(filled))

    assert _step(profile, "Whirlpool")["temperature"] == 75


def test_dry_hop_time_agrees_between_json_and_beerxml_exports():
    # BrewFather JSON reports Dry Hop time in days, BeerXML always in minutes.
    # Both exports of the same recipe must resolve to the same contact duration.
    json_recipe = _load_brewfather(WHEAT_ALE_JSON)
    xml_recipe = parse_beerxml(
        (DATA_DIR / "Brewfather_BeerXML_AmericanWheatAle_20260828.xml").read_text(
            encoding="iso-8859-1"
        )
    )

    def dry_hop_minutes(recipe):
        for hop in recipe.ingredients.hop_additions:
            if hop.timing and hop.timing.use == "add_to_fermentation":
                unit, value = hop.timing.duration.unit, hop.timing.duration.value
                return value * 1440 if unit == "day" else value
        return None

    assert dry_hop_minutes(json_recipe) == dry_hop_minutes(xml_recipe) == 4320


@pytest.mark.parametrize("path", JSON_FIXTURES, ids=lambda p: p.name)
def test_beerjson_export_reimports_unchanged(path):
    """Round trip: our own BeerJSON export must import back to the same recipe.
    Guards the import path against drift in the model it shares with the wizard."""
    recipe = _load_brewfather(path)
    reimported = parse_beerjson(to_beerjson_document(recipe))

    # Export fills schema-required placeholders the internal model leaves absent — an
    # unnamed rest comes back named "64 °C" — so compare the values, not the names.
    def rests(r):
        return [(s.step_temperature, s.step_time) for s in r.mash.mash_steps]

    assert reimported.name == recipe.name
    assert rests(reimported) == rests(recipe)
    assert reimported.boil == recipe.boil
    assert reimported.ingredients.hop_additions == recipe.ingredients.hop_additions
    # The real guarantee: placeholder or not, both compile to the same profile.
    assert compile_brewzilla_profile(reimported) == compile_brewzilla_profile(recipe)


def test_beerjson_import_prunes_properties_outside_our_subset():
    """Third-party BeerJSON carries properties our extra="forbid" subset omits;
    they must be dropped, not rejected."""
    document = {
        "beerjson": {
            "version": 1,
            "recipes": [
                {
                    "name": "Foreign IPA",
                    "type": "all grain",
                    "author": "Someone",
                    "batch_size": {"unit": "l", "value": 20},
                    "efficiency": {"brewhouse": {"unit": "%", "value": 72}},
                    # none of these are in our subset
                    "ibu_estimate": {"method": "Tinseth"},
                    "carbonation": {"unit": "vol", "value": 2.4},
                    "beer_pH": {"unit": "pH", "value": 4.4},
                    "created": "2026-08-28",
                    "packaging": {"name": "Kegged", "packaged_volume": {}},
                    "taste": {"notes": "resinous", "rating": 8},
                    "ingredients": {
                        "fermentable_additions": [
                            {
                                "name": "Pale Ale",
                                "type": "grain",
                                "amount": {"unit": "kg", "value": 5},
                                "grain_group": "base",  # not in our subset
                            }
                        ],
                        "hop_additions": [
                            {
                                "name": "Citra",
                                "amount": {"unit": "g", "value": 30},
                                "alpha_acid": {"unit": "%", "value": 12},
                                "beta_acid": {"unit": "%", "value": 4},  # not in our subset
                                "percent_lost": {"unit": "%", "value": 30},  # ditto
                                "timing": {
                                    "use": "add_to_boil",
                                    "duration": {"unit": "min", "value": 15},
                                },
                            }
                        ],
                    },
                    "mash": {
                        "name": "Single infusion",
                        "mash_steps": [
                            {
                                "name": "Saccharification",
                                "type": "infusion",
                                "step_temperature": {"unit": "C", "value": 67},
                                "step_time": {"unit": "min", "value": 60},
                                "start_ph": {"unit": "pH", "value": 5.4},  # not in our subset
                                "water_grain_ratio": {"unit": "l", "value": 3},  # ditto
                            }
                        ],
                    },
                    "boil": {"boil_time": {"unit": "min", "value": 60}},
                }
            ],
        }
    }

    recipe = parse_beerjson(document)

    assert recipe.name == "Foreign IPA"
    assert recipe.ingredients.hop_additions[0].alpha_acid.value == 12
    assert recipe.mash.mash_steps[0].step_temperature.value == 67
    profile = compile_brewzilla_profile(recipe)
    assert [s["name"] for s in profile["steps"][:2]] == ["Mash In", "Saccharification"]


def test_beerjson_import_drops_non_rest_mash_steps():
    """ "sparge" and "drain mash tun" are valid BeerJSON mash steps but are not rests —
    the compiler owns sparging via include_sparge, so they must not become rests."""
    document = {
        "beerjson": {
            "version": 1,
            "recipes": [
                {
                    "name": "With sparge step",
                    "type": "all grain",
                    "ingredients": {
                        "fermentable_additions": [
                            {
                                "name": "Pale Ale",
                                "type": "grain",
                                "amount": {"unit": "kg", "value": 5},
                            }
                        ]
                    },
                    "mash": {
                        "mash_steps": [
                            {
                                "name": "Sacch",
                                "type": "infusion",
                                "step_temperature": {"unit": "C", "value": 66},
                                "step_time": {"unit": "min", "value": 60},
                            },
                            {
                                "name": "Sparge",
                                "type": "sparge",
                                "step_temperature": {"unit": "C", "value": 76},
                                "step_time": {"unit": "min", "value": 15},
                            },
                            {
                                "name": "Drain",
                                "type": "drain mash tun",
                                "step_temperature": {"unit": "C", "value": 76},
                                "step_time": {"unit": "min", "value": 10},
                            },
                        ]
                    },
                    "boil": {"boil_time": {"unit": "min", "value": 60}},
                }
            ],
        }
    }

    recipe = parse_beerjson(document)

    assert [step.name for step in recipe.mash.mash_steps] == ["Sacch"]


def _import(fixture: str, **body):
    from fastapi.testclient import TestClient

    from app import app

    content = (DATA_DIR / fixture).read_text(encoding="utf-8")
    response = TestClient(app).post(
        "/api/profiles/import",
        json={"format": "brewfather_json", "content": content, **body},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_rest_end_alerts_name_the_rest_that_ended():
    """One toggle, but a text per rest: the alert has to say which rest ended, so it
    carries the rest's own step name (or its temperature when the file names none)."""
    profile = _import(
        "Brewfather_RECIPE_MunichHelles_20260828.json",
        overrides={"heat_power_pct": 90, "rest_power_pct": 50},
        rest_end_alerts=True,
    )

    ends = {
        step["name"]: [a["alertText"] for a in step["alerts"] if a["trigger"] == "StepEnd"]
        for step in profile["steps"]
    }
    # the file names its rests "Пауза 50 °C" — prefixing "Пауза завершена:" would stutter
    assert ends["Пауза 50 °C"] == ["Пауза 50 °C завершена"]
    assert ends["Пауза 63 °C"] == ["Пауза 63 °C завершена"]
    assert ends["Mash Out"] == ["Пауза завершена: Mash Out"]
    assert not any(step["name"].startswith("→") and step["alerts"] for step in profile["steps"])


def test_rest_end_alert_falls_back_to_the_rest_temperature():
    """The Corona Extra file leaves its rests unnamed, so the alert names them the same
    way the profile step is named — by temperature."""
    profile = _import("Brewfather_RECIPE_CoronaExtra_20260828.json", rest_end_alerts=True)

    ends = {
        step["name"]: [a["alertText"] for a in step["alerts"] if a["trigger"] == "StepEnd"]
        for step in profile["steps"]
    }
    assert ends["64 °C"] == ["Пауза завершена: 64 °C"]


def test_rest_end_alerts_are_off_by_default():
    profile = _import("Brewfather_RECIPE_MunichHelles_20260828.json")
    assert not any(a["trigger"] == "StepEnd" for step in profile["steps"] for a in step["alerts"])


def test_facade_dispatches_by_format():
    assert import_recipe(
        "brewfather_json",
        (DATA_DIR / "Brewfather_RECIPE_MunichHelles_20260828.json").read_text(encoding="utf-8"),
    ).name
    assert import_recipe(
        "beerjson",
        json.dumps(to_beerjson_document(_load_brewfather(WHEAT_ALE_JSON))),
    ).name


@pytest.mark.parametrize(
    ("source_format", "raw"),
    [
        ("brewfather_json", "{not json"),
        ("beerjson", "{not json"),
        ("beerjson", '{"beerjson": {"version": 1, "recipes": []}}'),
        ("beerxml", "<not-xml"),
    ],
)
def test_facade_rejects_unparsable_input(source_format, raw):
    with pytest.raises(ValueError):
        import_recipe(source_format, raw)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
