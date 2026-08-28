"""Conformance harness: our BeerJSON output must validate against the vendored official
schema. Also covers the Pydantic subset (beerjson_models.py) and the BrewZilla
overrides merge (brewzilla_overrides.py)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from features.recipes.beerjson_models import (
    BoilProcedureType,
    BoilStepType,
    CultureAdditionType,
    FermentableAdditionType,
    FermentationProcedureType,
    FermentationStepType,
    HopAdditionType,
    IngredientsType,
    MashProcedureType,
    MashStepType,
    MassType,
    MiscellaneousAdditionType,
    RecipeModel,
    StyleType,
    TemperatureType,
    TimeType,
    TimingType,
    UnitType,
    YieldType,
    to_beerjson_document,
)
from features.recipes.beerjson_schema import assert_valid_beerjson
from features.recipes.brewzilla_overrides import (
    BrewZillaOverrides,
    MashTemperatureAddition,
    merge_overrides,
)

MINIMAL_VALID_DOCUMENT = {
    "beerjson": {
        "version": 1,
        "recipes": [
            {
                "name": "Test Pale Ale",
                "type": "all grain",
                "author": "Tester",
                "efficiency": {"brewhouse": {"unit": "%", "value": 70}},
                "batch_size": {"unit": "l", "value": 20},
                "ingredients": {
                    "fermentable_additions": [
                        {
                            "name": "Pale Malt",
                            "type": "grain",
                            "yield": {"fine_grind": {"unit": "%", "value": 80}},
                            "color": {"unit": "SRM", "value": 3},
                            "amount": {"unit": "kg", "value": 5},
                        }
                    ]
                },
            }
        ],
    }
}


def test_minimal_document_is_schema_valid():
    assert_valid_beerjson(MINIMAL_VALID_DOCUMENT)


def test_document_with_unknown_field_is_rejected():
    broken = {
        "beerjson": {
            "version": 1,
            "recipes": [
                {
                    **MINIMAL_VALID_DOCUMENT["beerjson"]["recipes"][0],
                    "not_a_beerjson_field": "surprise",
                }
            ],
        }
    }
    with pytest.raises(ValueError, match="violates BeerJSON schema"):
        assert_valid_beerjson(broken)


def test_document_with_invalid_enum_is_rejected():
    broken = {
        "beerjson": {
            "version": 1,
            "recipes": [
                {**MINIMAL_VALID_DOCUMENT["beerjson"]["recipes"][0], "type": "not-a-real-type"}
            ],
        }
    }
    with pytest.raises(ValueError, match="violates BeerJSON schema"):
        assert_valid_beerjson(broken)


def _minimal_recipe() -> RecipeModel:
    return RecipeModel(
        name="Minimal Ale",
        notes="A minimal recipe with a single fermentable.",
        ingredients=IngredientsType(
            fermentable_additions=[
                FermentableAdditionType(
                    name="Pale Malt", type="grain", amount=MassType(unit="kg", value=5)
                )
            ]
        ),
    )


def _witbier_recipe() -> RecipeModel:
    boil_use = "add_to_boil"
    return RecipeModel(
        name="Белое поле",
        notes="Witbier: protein rest, three mash steps, 60 min boil, coriander and peel late, "
        "Belgian wit yeast at 21.5 °C.",
        style=StyleType(name="Witbier"),
        ingredients=IngredientsType(
            fermentable_additions=[
                FermentableAdditionType(
                    name="Pilsner malt",
                    type="grain",
                    color={"unit": "EBC", "value": 3},
                    yield_=YieldType(fine_grind={"unit": "%", "value": 81}),
                    amount=MassType(unit="kg", value=3),
                ),
                FermentableAdditionType(
                    name="Wheat malt",
                    type="grain",
                    color={"unit": "EBC", "value": 4},
                    yield_=YieldType(fine_grind={"unit": "%", "value": 80}),
                    amount=MassType(unit="kg", value=2),
                ),
                FermentableAdditionType(
                    name="Flaked oats",
                    type="grain",
                    color={"unit": "EBC", "value": 3},
                    yield_=YieldType(fine_grind={"unit": "%", "value": 70}),
                    amount=MassType(unit="kg", value=0.3),
                ),
                FermentableAdditionType(
                    name="Honey",
                    type="honey",
                    color={"unit": "EBC", "value": 1},
                    yield_=YieldType(fine_grind={"unit": "%", "value": 100}),
                    amount=MassType(unit="kg", value=0.2),
                ),
            ],
            hop_additions=[
                HopAdditionType(
                    name="Saaz",
                    alpha_acid={"unit": "%", "value": 4},
                    amount=MassType(unit="g", value=20),
                    timing=TimingType(use=boil_use, duration=TimeType(unit="min", value=60)),
                ),
                HopAdditionType(
                    name="Styrian Golding",
                    alpha_acid={"unit": "%", "value": 5},
                    amount=MassType(unit="g", value=10),
                    timing=TimingType(use=boil_use, duration=TimeType(unit="min", value=15)),
                ),
            ],
            culture_additions=[
                CultureAdditionType(
                    name="Belgian Wit Ale",
                    type="ale",
                    form="dry",
                    amount=UnitType(unit="pkg", value=1),
                )
            ],
            miscellaneous_additions=[
                MiscellaneousAdditionType(
                    name="Coriander seeds",
                    type="spice",
                    amount=MassType(unit="g", value=10),
                    timing=TimingType(use=boil_use, duration=TimeType(unit="min", value=10)),
                ),
                MiscellaneousAdditionType(
                    name="Bitter orange peel",
                    type="spice",
                    amount=MassType(unit="g", value=5),
                    timing=TimingType(use=boil_use, duration=TimeType(unit="min", value=10)),
                ),
            ],
        ),
        mash=MashProcedureType(
            mash_steps=[
                MashStepType(
                    type="temperature",
                    step_temperature=TemperatureType(unit="C", value=45),
                    step_time=TimeType(unit="min", value=15),
                ),
                MashStepType(
                    type="temperature",
                    step_temperature=TemperatureType(unit="C", value=62),
                    step_time=TimeType(unit="min", value=30),
                ),
                MashStepType(
                    type="temperature",
                    step_temperature=TemperatureType(unit="C", value=72),
                    step_time=TimeType(unit="min", value=30),
                ),
                MashStepType(
                    name="Mash Out",
                    type="temperature",
                    step_temperature=TemperatureType(unit="C", value=78),
                    step_time=TimeType(unit="min", value=5),
                ),
            ]
        ),
        boil=BoilProcedureType(boil_time=TimeType(unit="min", value=60)),
        fermentation=FermentationProcedureType(
            fermentation_steps=[
                FermentationStepType(
                    name="Primary", start_temperature=TemperatureType(unit="C", value=21.5)
                )
            ]
        ),
    )


def _whirlpool_recipe() -> RecipeModel:
    boil_time = TimeType(unit="min", value=60)
    return RecipeModel(
        name="Whirlpool IPA",
        notes="Boil 60 minutes then whirlpool 15 minutes with a late hop addition.",
        ingredients=IngredientsType(
            fermentable_additions=[
                FermentableAdditionType(
                    name="Pale Malt", type="grain", amount=MassType(unit="kg", value=5)
                )
            ],
            hop_additions=[
                HopAdditionType(
                    name="Citra",
                    amount=MassType(unit="g", value=30),
                    timing=TimingType(use="add_to_boil", time=boil_time),
                )
            ],
            culture_additions=[
                CultureAdditionType(name="US-05", amount=UnitType(unit="pkg", value=1))
            ],
            miscellaneous_additions=[
                MiscellaneousAdditionType(name="Whirlfloc", amount=UnitType(unit="each", value=1))
            ],
        ),
        boil=BoilProcedureType(
            boil_time=boil_time,
            boil_steps=[
                BoilStepType(step_time=boil_time),
                BoilStepType(
                    name="Whirlpool",
                    start_temperature=TemperatureType(unit="C", value=80),
                    step_time=TimeType(unit="min", value=15),
                ),
            ],
        ),
    )


@pytest.mark.parametrize(
    "build_recipe",
    [_minimal_recipe, _witbier_recipe, _whirlpool_recipe],
    ids=["minimal", "witbier", "whirlpool"],
)
def test_recipe_model_exports_to_schema_valid_document(build_recipe):
    assert_valid_beerjson(to_beerjson_document(build_recipe()))


def test_yield_serializes_under_alias_without_null():
    recipe = _witbier_recipe()
    dumped = recipe.model_dump(by_alias=True, exclude_none=True)
    fermentable = dumped["ingredients"]["fermentable_additions"][0]
    assert "yield" in fermentable
    assert "yield_" not in fermentable
    assert "producer" not in fermentable


def test_merge_overrides_user_wins_over_extracted():
    extracted = BrewZillaOverrides(mash_in_temperature_c=64, include_sparge=True)
    user = BrewZillaOverrides(mash_in_temperature_c=66)
    merged = merge_overrides(user, extracted)
    assert merged.mash_in_temperature_c == 66
    assert merged.include_sparge is True


def test_merge_overrides_none_does_not_clobber():
    extracted = BrewZillaOverrides(
        mash_additions=[MashTemperatureAddition(text="Add oats", temperature_c=65)]
    )
    merged = merge_overrides(None, extracted)
    assert merged.mash_additions[0].text == "Add oats"


def test_merge_overrides_both_none_is_empty():
    merged = merge_overrides(None, None)
    assert merged.model_dump(exclude_none=True) == {}


def test_culture_and_misc_without_amount_export_schema_valid():
    """Russian sources routinely name a yeast with no quantity ("Дрожжи: Сафэль S-04").
    The amount stays absent internally instead of being invented as "1 pkg"; the
    schema-required field is filled with a zero placeholder only at export."""
    recipe = _minimal_recipe()
    recipe = recipe.model_copy(
        update={
            "ingredients": recipe.ingredients.model_copy(
                update={
                    "culture_additions": [CultureAdditionType(name="Сафэль S-04", type="ale")],
                    "miscellaneous_additions": [
                        MiscellaneousAdditionType(name="Whirlfloc", type="fining")
                    ],
                }
            )
        }
    )

    document = to_beerjson_document(recipe)

    assert recipe.ingredients.culture_additions[0].amount is None
    assert_valid_beerjson(document)
    exported = document["beerjson"]["recipes"][0]["ingredients"]
    assert exported["culture_additions"][0]["amount"] == {"unit": "pkg", "value": 0}
    assert exported["miscellaneous_additions"][0]["amount"] == {"unit": "g", "value": 0}


def test_whirlpool_boil_step_without_step_time_is_accepted():
    """A stand stated only by temperature ("хмель на 95 °C") has no duration; rejecting
    it used to fail the whole extraction and drop the step."""
    boil_time = TimeType(unit="min", value=60)
    recipe = RecipeModel(
        name="Untimed Whirlpool",
        notes="Whirlpool step without step_time compiles to a manual-advance step.",
        ingredients=IngredientsType(
            fermentable_additions=[
                FermentableAdditionType(
                    name="Pale Malt", type="grain", amount=MassType(unit="kg", value=5)
                )
            ]
        ),
        boil=BoilProcedureType(
            boil_time=boil_time,
            boil_steps=[
                BoilStepType(step_time=boil_time),
                BoilStepType(
                    name="Whirlpool", start_temperature=TemperatureType(unit="C", value=95)
                ),
            ],
        ),
    )
    assert recipe.boil.boil_steps[1].step_time is None
    assert_valid_beerjson(to_beerjson_document(recipe))
