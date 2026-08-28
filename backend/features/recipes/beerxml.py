"""BeerXML recipe export -> RecipeModel.

Standard BeerXML units apply throughout: FERMENTABLE/HOP AMOUNT is always kg, TIME is
always minutes (including for "Dry Hop", unlike BrewFather's JSON export which reports
dry-hop time in days). MISC/YEAST amounts are read from DISPLAY_AMOUNT ("2.5 g", "2 pkg")
since AMOUNT there is unit-ambiguous (AMOUNT_IS_WEIGHT only distinguishes weight/volume).
"""

import re
import xml.etree.ElementTree as ET

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

_NUMERIC_PREFIX_RE = re.compile(r"-?\d+(?:\.\d+)?")
_DISPLAY_AMOUNT_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*([A-Za-z]+)\s*$")

# Stand temperature for a hopstand the file implies but cannot state — see
# _whirlpool_temperature. Only a default: a temperature present in the file wins.
WHIRLPOOL_TEMPERATURE_C = 80.0


def _text(elem: ET.Element | None, tag: str) -> str | None:
    if elem is None:
        return None
    child = elem.find(tag)
    return clean_text(child.text) if child is not None else None


def _number(elem: ET.Element | None, tag: str) -> float | None:
    text = _text(elem, tag)
    if text is None:
        return None
    match = _NUMERIC_PREFIX_RE.match(text)
    return float(match.group()) if match else None


def _display_amount(elem: ET.Element) -> MassType | VolumeType | UnitType | None:
    text = _text(elem, "DISPLAY_AMOUNT")
    if not text:
        return None
    match = _DISPLAY_AMOUNT_RE.match(text)
    if not match:
        return None
    value, unit = float(match.group(1)), match.group(2).lower()
    if unit in ("g", "kg", "mg", "oz", "lb"):
        return MassType(unit=unit, value=value)
    if unit in ("ml", "l"):
        return VolumeType(unit=unit, value=value)
    if unit == "pkg":
        return UnitType(unit="pkg", value=value)
    return None


def _fermentable(elem: ET.Element) -> FermentableAdditionType | None:
    amount_kg = _number(elem, "AMOUNT")
    if not amount_kg:  # the model requires a mass; nothing usable is left without one
        return None
    return FermentableAdditionType(
        name=named(_text(elem, "NAME"), "Fermentable"),
        type=fermentable_type(_text(elem, "TYPE")),
        origin=_text(elem, "ORIGIN"),
        producer=_text(elem, "SUPPLIER"),
        amount=MassType(unit="kg", value=amount_kg),
    )


def _hop(elem: ET.Element, boil_time_min: float | None) -> HopAdditionType | None:
    amount_kg = _number(elem, "AMOUNT")
    if not amount_kg:  # the model requires a mass; nothing usable is left without one
        return None
    alpha = _number(elem, "ALPHA")
    return HopAdditionType(
        name=named(_text(elem, "NAME"), "Hop"),
        origin=_text(elem, "ORIGIN"),
        form=hop_form(_text(elem, "FORM")),
        alpha_acid=PercentType(unit="%", value=alpha) if alpha is not None else None,
        amount=MassType(unit="g", value=amount_kg * 1000),
        timing=ingredient_timing(_text(elem, "USE"), _number(elem, "TIME"), "min", boil_time_min),
    )


def _misc(elem: ET.Element, boil_time_min: float | None) -> MiscellaneousAdditionType | None:
    amount = _display_amount(elem)
    if amount is None:
        weight_kg = _number(elem, "AMOUNT")
        if weight_kg is not None:
            is_weight = lower(_text(elem, "AMOUNT_IS_WEIGHT")) != "false"
            amount = (
                MassType(unit="kg", value=weight_kg)
                if is_weight
                else VolumeType(unit="l", value=weight_kg)
            )
    if amount is None and not _text(elem, "NAME"):
        return None
    return MiscellaneousAdditionType(
        name=named(_text(elem, "NAME"), "Addition"),
        type=misc_type(_text(elem, "TYPE")),
        amount=amount,
        timing=ingredient_timing(_text(elem, "USE"), _number(elem, "TIME"), "min", boil_time_min),
    )


def _culture(elem: ET.Element) -> CultureAdditionType | None:
    amount = _display_amount(elem)
    if amount is None and not _text(elem, "NAME"):
        return None
    attenuation = _number(elem, "ATTENUATION")
    return CultureAdditionType(
        name=named(_text(elem, "NAME"), "Yeast"),
        type=culture_type(_text(elem, "TYPE")),
        form=culture_form(_text(elem, "FORM")),
        producer=_text(elem, "LABORATORY"),
        amount=amount,
        attenuation=PercentType(unit="%", value=attenuation) if attenuation is not None else None,
    )


def _mash(recipe_elem: ET.Element) -> MashProcedureType | None:
    steps = []
    for step in recipe_elem.findall("MASH/MASH_STEPS/MASH_STEP"):
        temp = _number(step, "STEP_TEMP")
        time = _number(step, "STEP_TIME")
        if temp is None or time is None:
            continue
        steps.append(
            MashStepType(
                name=_text(step, "NAME"),
                type="infusion" if lower(_text(step, "TYPE")) == "infusion" else "temperature",
                step_temperature=TemperatureType(unit="C", value=temp),
                step_time=TimeType(unit="min", value=time),
            )
        )
    return MashProcedureType(mash_steps=steps) if steps else None


def _whirlpool_temperature(elems: list[ET.Element]) -> float:
    """Temperature for the hopstand the Aroma additions imply.

    BeerXML 1.0 has no hopstand temperature: Brewfather writes <TEMPERATURE/> and
    <HOP_TEMP/> empty even when the recipe has one (its JSON export carries the same
    stand as avgWeightedHopstandTemp). Left unset, the compiler falls back to the boil
    temperature and stands the aroma hops at 100 °C — a boil, not a hopstand. So: use
    whatever the exporter did fill in, otherwise a typical hopstand.
    """
    stated = [
        value
        for elem in elems
        for value in (_number(elem, "HOP_TEMP"), _number(elem, "TEMPERATURE"))
        if value is not None
    ]
    return max(stated) if stated else WHIRLPOOL_TEMPERATURE_C


def _boil(
    boil_time_min: float | None, hops: list[ET.Element], miscs: list[ET.Element]
) -> BoilProcedureType | None:
    if boil_time_min is None:
        return None
    whirlpool = [
        elem
        for elem in (*hops, *miscs)
        if is_whirlpool_use(_text(elem, "USE")) and _number(elem, "TIME") is not None
    ]
    boil_steps = None
    if whirlpool:
        boil_steps = [
            BoilStepType(name="Boil"),
            BoilStepType(
                name="Whirlpool",
                start_temperature=TemperatureType(
                    unit="C", value=_whirlpool_temperature(whirlpool)
                ),
                step_time=TimeType(unit="min", value=max(_number(e, "TIME") for e in whirlpool)),
            ),
        ]
    return BoilProcedureType(
        boil_time=TimeType(unit="min", value=boil_time_min), boil_steps=boil_steps
    )


def parse_beerxml(xml_text: str) -> RecipeModel:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as error:
        raise ValueError(f"invalid BeerXML: {error}") from error

    recipe_elem = root if root.tag == "RECIPE" else root.find(".//RECIPE")
    if recipe_elem is None:
        raise ValueError("no <RECIPE> element found in BeerXML")

    hops = recipe_elem.findall("HOPS/HOP")
    fermentables = recipe_elem.findall("FERMENTABLES/FERMENTABLE")
    miscs = recipe_elem.findall("MISCS/MISC")
    yeasts = recipe_elem.findall("YEASTS/YEAST")
    boil_time = _number(recipe_elem, "BOIL_TIME")

    style_name = _text(recipe_elem.find("STYLE"), "NAME")
    batch_size = _number(recipe_elem, "BATCH_SIZE")
    efficiency = _number(recipe_elem, "EFFICIENCY")
    og = _number(recipe_elem, "OG")
    fg = _number(recipe_elem, "FG")
    abv = _number(recipe_elem, "ABV")

    return RecipeModel(
        name=_text(recipe_elem, "NAME") or "Imported recipe",
        type=recipe_type(_text(recipe_elem, "TYPE")),
        author=_text(recipe_elem, "BREWER"),
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
        notes=_text(recipe_elem, "NOTES"),
        ingredients=IngredientsType(
            fermentable_additions=[f for f in (_fermentable(e) for e in fermentables) if f] or None,
            hop_additions=[h for h in (_hop(e, boil_time) for e in hops) if h] or None,
            culture_additions=[c for c in (_culture(e) for e in yeasts) if c] or None,
            miscellaneous_additions=[m for m in (_misc(e, boil_time) for e in miscs) if m] or None,
        ),
        mash=_mash(recipe_elem),
        boil=_boil(boil_time, hops, miscs),
    )
