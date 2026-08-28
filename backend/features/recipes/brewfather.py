"""BrewFather recipe JSON export -> RecipeModel.

Field units follow BrewFather's API convention (confirmed against the vendored
samples in backend/tests/data/): fermentable amounts in kg, hop amounts in g,
misc/yeast amounts carry their own explicit "unit" field. Hop/misc "time" is
minutes except "Dry Hop", which BrewFather reports in days.
"""

from .beerjson_models import (
    BoilProcedureType,
    BoilStepType,
    CultureAdditionType,
    EfficiencyType,
    FermentableAdditionType,
    GravityType,
    HopAdditionType,
    IngredientsType,
    MashProcedureType,
    MashStepType,
    MassType,
    MiscellaneousAdditionType,
    PercentType,
    RecipeModel,
    StyleType,
    TemperatureType,
    TimeType,
    UnitType,
    VolumeType,
)
from .import_common import (
    clean_text,
    culture_form,
    culture_type,
    fermentable_type,
    hop_form,
    ingredient_timing,
    is_whirlpool_use,
    lower,
    misc_type,
    named,
    recipe_type,
)


def _fermentable(item: dict) -> FermentableAdditionType | None:
    amount = item.get("amount")
    if not amount:  # the model requires a mass; nothing usable is left without one
        return None
    return FermentableAdditionType(
        name=named(item.get("name"), "Fermentable"),
        type=fermentable_type(item.get("type")),
        origin=clean_text(item.get("origin")),
        producer=clean_text(item.get("supplier")),
        amount=MassType(unit="kg", value=amount),
    )


def _hop(item: dict, boil_time_min: float | None) -> HopAdditionType | None:
    amount = item.get("amount")
    if not amount:  # the model requires a mass; nothing usable is left without one
        return None
    alpha = item.get("alpha")
    use = item.get("use")
    time_unit = "day" if lower(use) == "dry hop" else "min"
    return HopAdditionType(
        name=named(item.get("name"), "Hop"),
        origin=clean_text(item.get("origin")),
        form=hop_form(item.get("type")),
        alpha_acid=PercentType(unit="%", value=alpha) if alpha is not None else None,
        amount=MassType(unit="g", value=amount),
        timing=ingredient_timing(use, item.get("time"), time_unit, boil_time_min),
    )


def _misc_amount(item: dict) -> MassType | VolumeType | UnitType | None:
    value = item.get("amount")
    if value is None:
        return None
    unit = lower(item.get("unit")) or "g"
    if unit in ("g", "kg", "mg", "oz", "lb"):
        return MassType(unit=unit, value=value)
    if unit in ("ml", "l"):
        return VolumeType(unit=unit, value=value)
    return None


def _misc(item: dict, boil_time_min: float | None) -> MiscellaneousAdditionType | None:
    amount = _misc_amount(item)
    if not amount and not clean_text(item.get("name")):
        return None
    time_unit = "day" if item.get("timeIsDays") else "min"
    return MiscellaneousAdditionType(
        name=named(item.get("name"), "Addition"),
        type=misc_type(item.get("type")),
        amount=amount,
        timing=ingredient_timing(item.get("use"), item.get("time"), time_unit, boil_time_min),
    )


def _culture_amount(item: dict) -> MassType | VolumeType | UnitType | None:
    value = item.get("amount")
    if value is None:
        return None
    unit = lower(item.get("unit"))
    if unit in ("g", "kg"):
        return MassType(unit=unit, value=value)
    if unit in ("ml", "l"):
        return VolumeType(unit=unit, value=value)
    if unit == "pkg":
        return UnitType(unit="pkg", value=value)
    return None


def _culture(item: dict) -> CultureAdditionType | None:
    amount = _culture_amount(item)
    if not amount and not clean_text(item.get("name")):
        return None
    attenuation = item.get("attenuation")
    return CultureAdditionType(
        name=named(item.get("name"), "Yeast"),
        type=culture_type(item.get("type")),
        form=culture_form(item.get("form")),
        producer=clean_text(item.get("laboratory")),
        amount=amount,
        attenuation=PercentType(unit="%", value=attenuation) if attenuation is not None else None,
    )


def _mash(data: dict | None) -> MashProcedureType | None:
    steps = []
    for step in (data or {}).get("steps") or []:
        temp = step.get("stepTemp")
        time = step.get("stepTime")
        if temp is None or time is None:
            continue
        steps.append(
            MashStepType(
                name=clean_text(step.get("name")),
                type="infusion" if lower(step.get("type")) == "infusion" else "temperature",
                step_temperature=TemperatureType(unit="C", value=temp),
                step_time=TimeType(unit="min", value=time),
            )
        )
    return MashProcedureType(mash_steps=steps) if steps else None


def _boil(
    boil_time_min: float | None,
    hops_raw: list[dict],
    miscs_raw: list[dict],
    whirlpool_temp_c: float | None,
) -> BoilProcedureType | None:
    if boil_time_min is None:
        return None
    whirlpool_times = [
        item.get("time")
        for item in (*hops_raw, *miscs_raw)
        if is_whirlpool_use(item.get("use")) and item.get("time") is not None
    ]
    boil_steps = None
    if whirlpool_times:
        boil_steps = [
            BoilStepType(name="Boil"),
            BoilStepType(
                name="Whirlpool",
                start_temperature=(
                    TemperatureType(unit="C", value=whirlpool_temp_c)
                    if whirlpool_temp_c is not None
                    else None
                ),
                step_time=TimeType(unit="min", value=max(whirlpool_times)),
            ),
        ]
    return BoilProcedureType(
        boil_time=TimeType(unit="min", value=boil_time_min), boil_steps=boil_steps
    )


def parse_brewfather_json(data: dict) -> RecipeModel:
    if "name" not in data and "fermentables" not in data:
        raise ValueError("file does not look like a BrewFather recipe export")

    boil_time = data.get("boilTime")
    hops_raw = data.get("hops") or []
    miscs_raw = data.get("miscs") or []

    fermentables = [f for f in (_fermentable(x) for x in data.get("fermentables") or []) if f]
    hops = [h for h in (_hop(x, boil_time) for x in hops_raw) if h]
    cultures = [c for c in (_culture(x) for x in data.get("yeasts") or []) if c]
    miscs = [m for m in (_misc(x, boil_time) for x in miscs_raw) if m]

    style_name = clean_text((data.get("style") or {}).get("name"))
    batch_size = data.get("batchSize")
    efficiency = data.get("efficiency")
    og = data.get("og")
    fg = data.get("fg")
    abv = data.get("abv")

    return RecipeModel(
        name=clean_text(data.get("name")) or "Imported recipe",
        type=recipe_type(data.get("type")),
        author=clean_text(data.get("author")),
        style=StyleType(name=style_name) if style_name else None,
        batch_size=VolumeType(unit="l", value=batch_size) if batch_size else None,
        efficiency=(
            EfficiencyType(brewhouse=PercentType(unit="%", value=efficiency))
            if efficiency is not None
            else None
        ),
        original_gravity=GravityType(unit="sg", value=og) if og else None,
        final_gravity=GravityType(unit="sg", value=fg) if fg else None,
        alcohol_by_volume=PercentType(unit="%", value=abv) if abv is not None else None,
        notes=clean_text(data.get("notes")),
        ingredients=IngredientsType(
            fermentable_additions=fermentables or None,
            hop_additions=hops or None,
            culture_additions=cultures or None,
            miscellaneous_additions=miscs or None,
        ),
        mash=_mash(data.get("mash")),
        boil=_boil(boil_time, hops_raw, miscs_raw, data.get("avgWeightedHopstandTemp")),
    )
