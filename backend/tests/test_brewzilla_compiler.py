"""Tests for compile_brewzilla_profile: BeerJSON recipe + BrewZilla overrides -> profile."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from features.ai.beerjson_models import (
    BoilProcedureType,
    BoilStepType,
    CultureAdditionType,
    FermentableAdditionType,
    HopAdditionType,
    IngredientsType,
    MashProcedureType,
    MashStepType,
    MassType,
    RecipeModel,
    TemperatureType,
    TimeType,
    TimingType,
    UnitType,
)
from features.ai.brewzilla_compiler import compile_brewzilla_profile
from features.ai.brewzilla_overrides import (
    BrewZillaOverrides,
    MashTemperatureAddition,
    RestEndAlert,
)


def _fermentable(name="Pale Ale malt", kg=5.0):
    return FermentableAdditionType(name=name, type="grain", amount=MassType(unit="kg", value=kg))


def _hop(name="Cascade", g=20.0, *, duration_min=None, time_min=None):
    timing = None
    if duration_min is not None or time_min is not None:
        timing = TimingType(
            use="add_to_boil",
            duration=TimeType(unit="min", value=duration_min) if duration_min is not None else None,
            time=TimeType(unit="min", value=time_min) if time_min is not None else None,
        )
    return HopAdditionType(name=name, amount=MassType(unit="g", value=g), timing=timing)


def _rest(temp_c, minutes, *, name=None):
    return MashStepType(
        name=name,
        type="temperature",
        step_temperature=TemperatureType(unit="C", value=temp_c),
        step_time=TimeType(unit="min", value=minutes),
    )


def _base_recipe(*, mash_steps=None, boil_minutes=60, hop=None) -> RecipeModel:
    return RecipeModel(
        name="APA 23 L",
        notes="Single-step mash, 60 minute boil, late hop addition.",
        ingredients=IngredientsType(
            fermentable_additions=[_fermentable()],
            hop_additions=[hop or _hop(duration_min=15)],
            culture_additions=[
                CultureAdditionType(name="US-05", amount=UnitType(unit="pkg", value=1))
            ],
        ),
        mash=(
            MashProcedureType(mash_steps=mash_steps)
            if mash_steps is not None
            else MashProcedureType(mash_steps=[_rest(67, 60, name="Мальтозная пауза")])
        ),
        boil=BoilProcedureType(boil_time=TimeType(unit="min", value=boil_minutes)),
    )


def _step(profile, name):
    return next(step for step in profile["steps"] if step["name"] == name)


def test_rejects_missing_mash_and_mash_in():
    recipe = RecipeModel(
        name="No mash",
        notes="No mash steps and no mash-in override provided.",
        ingredients=IngredientsType(fermentable_additions=[_fermentable()]),
    )
    with pytest.raises(ValueError, match="mash-in temperature or at least one mash step"):
        compile_brewzilla_profile(recipe)


def test_rejects_boil_addition_outside_boil():
    recipe = _base_recipe(boil_minutes=60, hop=_hop(duration_min=70))
    with pytest.raises(ValueError, match="boil addition occurs outside the boil"):
        compile_brewzilla_profile(recipe)


def test_rejects_timed_addition_without_boil():
    recipe = _base_recipe(hop=_hop(duration_min=15))
    recipe = recipe.model_copy(update={"boil": None})
    with pytest.raises(ValueError, match="boil duration is required"):
        compile_brewzilla_profile(recipe)


def test_preserves_explicit_low_mash_in():
    recipe = _base_recipe(mash_steps=[_rest(45, 15)])
    overrides = BrewZillaOverrides(mash_in_temperature_c=38, mash_in_alert_text="Добавить солод")

    profile = compile_brewzilla_profile(recipe, overrides)

    assert [step["name"] for step in profile["steps"][:2]] == ["Mash In", "45 °C"]
    assert profile["steps"][0]["temperature"] == 38
    assert profile["steps"][0]["endType"] == "Manual"


def test_applies_power_and_pid_rules():
    recipe = _base_recipe()
    overrides = BrewZillaOverrides(heat_power_pct=90, rest_power_pct=50, mash_pid_enabled=True)

    profile = compile_brewzilla_profile(recipe, overrides)

    mash_in = profile["steps"][0]
    first_rest = _step(profile, "Мальтозная пауза")
    mash_out = _step(profile, "Mash Out")
    mash_out_transition = profile["steps"][profile["steps"].index(mash_out) - 1]
    boil = _step(profile, "Boil")
    assert mash_in["heatingUtilisation"] == 90
    assert first_rest["heatingUtilisation"] == 50
    assert first_rest["pidEnabled"] is True
    assert mash_out_transition["endType"] == "Temperature"
    assert mash_out_transition["heatingUtilisation"] == 90
    assert boil["heatingUtilisation"] == 90
    assert boil["pidEnabled"] is False


def test_applies_defaults_and_boil_timing():
    recipe = _base_recipe(
        mash_steps=[_rest(67, 60, name="Мальтозная пауза")],
        hop=_hop(duration_min=15),
    )
    recipe = recipe.model_copy(
        update={
            "ingredients": recipe.ingredients.model_copy(
                update={
                    "fermentable_additions": [
                        *recipe.ingredients.fermentable_additions,
                        FermentableAdditionType(
                            name="Sugar",
                            type="sugar",
                            amount=MassType(unit="g", value=100),
                            timing=TimingType(
                                use="add_to_boil", time=TimeType(unit="min", value=10)
                            ),
                        ),
                    ]
                }
            )
        }
    )
    overrides = BrewZillaOverrides(mash_out_end_alert_text="Mash Out завершён")

    profile = compile_brewzilla_profile(recipe, overrides)

    assert profile["steps"][0]["temperature"] == 70  # first rest (67) + MASH_IN_DELTA_C
    assert profile["steps"][0]["alerts"][0]["alertText"] == "Add grain"
    boil = _step(profile, "Boil")
    # iteration order is fermentable_additions, then hop_additions: sugar (600) before hop (2700)
    assert [alert["length"] for alert in boil["alerts"]] == [600, 2700]
    mash_out = _step(profile, "Mash Out")
    assert mash_out["temperature"] == 78
    assert mash_out["alerts"][0]["trigger"] == "StepEnd"
    assert profile["steps"][-1]["temperature"] == 20


def test_preserves_stage_temperatures():
    recipe = _base_recipe()
    overrides = BrewZillaOverrides(mash_out_temperature_c=76, sparge_temperature_c=77)

    profile = compile_brewzilla_profile(recipe, overrides)

    assert _step(profile, "Mash Out")["temperature"] == 76
    assert _step(profile, "Sparge")["temperature"] == 77


def test_preserves_explicit_mash_additions():
    recipe = _base_recipe()
    overrides = BrewZillaOverrides(
        mash_additions=[MashTemperatureAddition(text="Add prepared adjunct", temperature_c=33)]
    )

    profile = compile_brewzilla_profile(recipe, overrides)

    alerts = profile["steps"][0]["alerts"]
    assert alerts[1]["alertText"] == "Add prepared adjunct"
    assert alerts[1]["trigger"] == "Temperature"
    assert alerts[1]["temperature"] == 33


def test_preserves_whirlpool_without_temperature():
    recipe = _base_recipe(
        boil_minutes=60,
        hop=_hop(name="Citra", time_min=60),
    )
    recipe = recipe.model_copy(
        update={
            "boil": BoilProcedureType(
                boil_time=TimeType(unit="min", value=60),
                boil_steps=[
                    BoilStepType(step_time=TimeType(unit="min", value=60)),
                    BoilStepType(name="Whirlpool", step_time=TimeType(unit="min", value=5)),
                ],
            )
        }
    )

    profile = compile_brewzilla_profile(recipe)

    whirlpool = _step(profile, "Whirlpool")
    assert whirlpool["temperature"] == 100
    assert whirlpool["length"] == 300
    assert whirlpool["heatingUtilisation"] == 0
    assert whirlpool["pidEnabled"] is False
    assert whirlpool["alerts"][0]["length"] == 0


def test_compiles_untimed_whirlpool_from_stand_temperature():
    """A whirlpool stated as a temperature with no stand time ("во время охлаждения при
    95 градусах") is a manual-advance step carrying its hops as StepStart alerts."""
    recipe = _base_recipe(boil_minutes=90, hop=_hop(name="Цитра", g=28.0, time_min=90))
    recipe = recipe.model_copy(
        update={
            "boil": BoilProcedureType(
                boil_time=TimeType(unit="min", value=90),
                boil_steps=[
                    BoilStepType(),
                    BoilStepType(
                        name="Хмелестояние",
                        start_temperature=TemperatureType(unit="C", value=95),
                    ),
                ],
            )
        }
    )

    profile = compile_brewzilla_profile(recipe)

    assert _step(profile, "Boil")["temperature"] == 100
    assert not _step(profile, "Boil")["alerts"]
    whirlpool = _step(profile, "Хмелестояние")
    assert whirlpool["temperature"] == 95
    assert whirlpool["endType"] == "Manual"
    assert whirlpool["durationType"] == "Manual"
    assert whirlpool["length"] is None
    assert whirlpool["heatingUtilisation"] == 0
    assert [alert["alertText"] for alert in whirlpool["alerts"]] == ["28 g Цитра"]
    assert whirlpool["alerts"][0]["trigger"] == "StepStart"


def test_compiles_untimed_mash_rest_as_manual_step():
    """A rest stated without a duration ("затирание при 67°") is kept as a
    manual-advance rest instead of being dropped."""
    untimed = MashStepType(
        name="Осахаривание",
        type="temperature",
        step_temperature=TemperatureType(unit="C", value=67),
    )
    recipe = _base_recipe(mash_steps=[untimed, _rest(72, 20)])

    profile = compile_brewzilla_profile(recipe)

    rest = _step(profile, "Осахаривание")
    assert rest["temperature"] == 67
    assert rest["endType"] == "Manual"
    assert rest["durationType"] == "Manual"
    assert rest["length"] is None


def test_preserves_rest_end_alerts_and_final_mash_out():
    rests = [
        _rest(temperature, duration)
        for temperature, duration in [(45, 15), (50, 10), (63, 30), (65, 20), (72, 20), (78, 5)]
    ]
    recipe = _base_recipe(mash_steps=rests)
    overrides = BrewZillaOverrides(
        heat_power_pct=90,
        rest_power_pct=50,
        mash_pid_enabled=True,
        mash_out_end_alert_text="Mash Out завершён",
        sparge_alert_text="Начать промывку",
        rest_end_alerts=[
            RestEndAlert(rest_index=index, text=f"Rest {temperature} °C done")
            for index, (temperature, _) in enumerate(
                [(45, 15), (50, 10), (63, 30), (65, 20), (72, 20), (78, 5)]
            )
        ],
    )

    profile = compile_brewzilla_profile(recipe, overrides)

    assert profile["steps"][1]["name"] == "45 °C"  # no explicit name -> temperature fallback
    assert profile["steps"][1]["heatingUtilisation"] == 50
    assert [step["name"] for step in profile["steps"]].count("Mash Out") == 1
    mash_out = _step(profile, "Mash Out")
    assert mash_out["length"] == 300
    assert mash_out["alerts"][0]["alertText"] == "Mash Out завершён"
    assert mash_out["alerts"][0]["trigger"] == "StepEnd"
    rest_steps = [
        step
        for step in profile["steps"]
        if step["name"].endswith("°C") and not step["name"].startswith("→")
    ]
    assert all(
        any(alert["trigger"] == "StepEnd" for alert in step["alerts"]) for step in rest_steps
    )
    # the mash-out rest (78 °C, last, temperature >= MASH_OUT_DETECT_MIN_C) is recognized and
    # therefore does NOT also get a rest_end_alerts entry of its own (index 5 was consumed).
    assert "Rest 78 °C done" not in [
        alert["alertText"] for step in profile["steps"] for alert in step["alerts"]
    ]
    sparge = _step(profile, "Sparge")
    assert sparge["alerts"][0]["trigger"] == "StepStart"
    assert sparge["heatingUtilisation"] == 0
    assert sparge["pidEnabled"] is False
    assert all(
        step["pumpEnabled"] is None and step["pumpUtilisation"] is None for step in profile["steps"]
    )


def test_honors_disabled_setup_features():
    recipe = _base_recipe()
    overrides = BrewZillaOverrides(
        include_temperature_alerts=False, include_sparge=False, include_mash_out=False
    )

    profile = compile_brewzilla_profile(recipe, overrides)

    names = [step["name"] for step in profile["steps"]]
    assert "Mash Out" not in names
    assert "Sparge" not in names
    assert all(
        alert["trigger"] != "Temperature" for step in profile["steps"] for alert in step["alerts"]
    )


def test_mash_out_detected_by_russian_name_below_temperature_threshold():
    recipe = _base_recipe(
        mash_steps=[_rest(67, 60, name="Мальтозная пауза"), _rest(70, 5, name="Мэш аут")]
    )

    profile = compile_brewzilla_profile(recipe)

    mash_out = _step(profile, "Мэш аут")
    assert mash_out["temperature"] == 70
    assert mash_out["length"] == 300


def test_mash_out_name_matches_hyphenated_spelling():
    recipe = _base_recipe(
        mash_steps=[_rest(67, 60, name="Мальтозная пауза"), _rest(70, 5, name="Мэш-аут")]
    )

    profile = compile_brewzilla_profile(recipe)

    assert _step(profile, "Мэш-аут")["length"] == 300


def test_disabled_mash_out_drops_recipe_mash_out_rest_entirely():
    recipe = _base_recipe(
        mash_steps=[_rest(67, 60, name="Мальтозная пауза"), _rest(78, 5, name="Mash Out")]
    )
    overrides = BrewZillaOverrides(include_mash_out=False)

    profile = compile_brewzilla_profile(recipe, overrides)

    names = [step["name"] for step in profile["steps"]]
    assert "Mash Out" not in names
    # the 78 °C/5 min mash-out rest must be dropped entirely, not just renamed away;
    # the default Sparge step (also 78 °C) is unrelated and stays.
    assert not any(step["temperature"] == 78 and step["length"] == 300 for step in profile["steps"])


def test_converts_fahrenheit_and_hours_to_celsius_and_seconds():
    recipe = _base_recipe(
        mash_steps=[
            MashStepType(
                name="Single infusion",
                type="temperature",
                step_temperature=TemperatureType(unit="F", value=152),
                step_time=TimeType(unit="hr", value=1),
            )
        ],
        boil_minutes=60,
    )

    profile = compile_brewzilla_profile(recipe)

    rest = _step(profile, "Single infusion")
    assert rest["temperature"] == pytest.approx((152 - 32) * 5 / 9)
    assert rest["length"] == 3600


def test_recipe_without_mash_compiles_with_mash_in_override():
    recipe = RecipeModel(
        name="Extract kit",
        notes="No mash procedure; steeping only, mash-in override provided.",
        ingredients=IngredientsType(fermentable_additions=[_fermentable()]),
    )
    overrides = BrewZillaOverrides(mash_in_temperature_c=64)

    profile = compile_brewzilla_profile(recipe, overrides)

    assert profile["steps"][0]["temperature"] == 64
    assert profile["steps"][0]["name"] == "Mash In"


def test_overrides_take_priority_over_extracted_values():
    recipe = _base_recipe()
    extracted = BrewZillaOverrides(mash_in_temperature_c=70)
    user = BrewZillaOverrides(mash_in_temperature_c=66)
    from features.ai.brewzilla_overrides import merge_overrides

    profile = compile_brewzilla_profile(recipe, merge_overrides(user, extracted))

    assert profile["steps"][0]["temperature"] == 66
