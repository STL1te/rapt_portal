"""Pydantic subset of BeerJSON 1.0. Field names, shapes and enums mirror the official
schema exactly; every serialized document must validate against vendor/beerjson.

Some fields the official schema marks required are optional here (principle 10 of
docs/beerjson-migration-plan.md): real recipes are often written without them (hop
alpha acid, culture type/form, mash grain temperature, step names, ...). Those fields
stay absent in the internal model - inventing a value would corrupt training data - and
`to_beerjson_document` fills schema-mandated placeholders only at the export boundary.
"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _BJ(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, populate_by_name=True)


class MassType(_BJ):
    unit: Literal["mg", "g", "kg", "lb", "oz"]
    value: float = Field(gt=0, allow_inf_nan=False)


class VolumeType(_BJ):
    unit: Literal["ml", "l", "tsp", "tbsp", "floz", "cup", "pt", "qt", "gal", "bbl"]
    value: float = Field(gt=0, allow_inf_nan=False)


class UnitType(_BJ):  # counted things: packets, oranges, tablets
    unit: Literal["1", "unit", "each", "dimensionless", "pkg"]
    value: float = Field(gt=0, allow_inf_nan=False)


class TemperatureType(_BJ):
    unit: Literal["C", "F"]
    value: float = Field(allow_inf_nan=False)


class TimeType(_BJ):
    unit: Literal["sec", "min", "hr", "day", "week"]
    value: float = Field(ge=0, allow_inf_nan=False)


class PercentType(_BJ):
    unit: Literal["%"]
    value: float = Field(allow_inf_nan=False)


class GravityType(_BJ):
    unit: Literal["sg", "plato", "brix"]
    value: float = Field(gt=0, allow_inf_nan=False)


class ColorType(_BJ):
    unit: Literal["EBC", "Lovi", "SRM"]
    value: float = Field(allow_inf_nan=False)


class TimingType(_BJ):
    # `use` is declared first: llama.cpp grammars force schema property order, and
    # models naturally emit `use` before time/duration — the reverse order made
    # constrained decoding silently drop durations.
    use: Literal["add_to_mash", "add_to_boil", "add_to_fermentation", "add_to_package"] | None = (
        None
    )
    time: TimeType | None = None
    duration: TimeType | None = None
    continuous: bool | None = None
    specific_gravity: GravityType | None = None


class YieldType(_BJ):
    fine_grind: PercentType | None = None
    potential: GravityType | None = None


class FermentableAdditionType(_BJ):
    name: str = Field(min_length=1, max_length=300)
    type: Literal["grain", "extract", "dry extract", "sugar", "fruit", "juice", "honey", "other"]
    origin: str | None = Field(default=None, min_length=1, max_length=100)
    producer: str | None = Field(default=None, min_length=1, max_length=100)
    color: ColorType | None = None  # required by schema; often unstated, see module docstring
    yield_: YieldType | None = Field(default=None, alias="yield")  # required by schema, see above
    amount: MassType | VolumeType
    timing: TimingType | None = None


class HopAdditionType(_BJ):
    name: str = Field(min_length=1, max_length=300)
    origin: str | None = Field(default=None, min_length=1, max_length=100)
    year: str | None = None
    form: Literal["extract", "leaf", "leaf (wet)", "pellet", "powder", "plug"] | None = None
    alpha_acid: PercentType | None = None  # required by schema; often unstated
    amount: MassType
    timing: TimingType | None = None  # required by schema; often unstated


class CultureAdditionType(_BJ):
    name: str = Field(min_length=1, max_length=300)
    type: (
        Literal[
            "ale",
            "bacteria",
            "brett",
            "champagne",
            "kveik",
            "lacto",
            "lager",
            "malolactic",
            "mixed-culture",
            "other",
            "pedio",
            "spontaneous",
            "wine",
        ]
        | None
    ) = None  # required by schema; often unstated
    form: Literal["liquid", "dry", "slant", "culture", "dregs"] | None = (
        None  # required by schema; often unstated
    )
    producer: str | None = Field(default=None, min_length=1, max_length=100)
    amount: MassType | VolumeType | UnitType
    attenuation: PercentType | None = None
    timing: TimingType | None = None


class MiscellaneousAdditionType(_BJ):
    name: str = Field(min_length=1, max_length=300)
    type: Literal["spice", "fining", "water agent", "herb", "flavor", "wood", "other"] | None = (
        None  # required by schema; often unstated
    )
    amount: MassType | VolumeType | UnitType
    timing: TimingType | None = None


class IngredientsType(_BJ):
    fermentable_additions: list[FermentableAdditionType] = Field(min_length=1)
    hop_additions: list[HopAdditionType] | None = None
    culture_additions: list[CultureAdditionType] | None = None
    miscellaneous_additions: list[MiscellaneousAdditionType] | None = None


class MashStepType(_BJ):
    name: str | None = Field(
        default=None, min_length=1, max_length=80
    )  # required by schema; often unstated, see module docstring
    type: Literal["infusion", "temperature", "decoction", "souring mash", "souring wort"]
    amount: VolumeType | None = None
    step_temperature: TemperatureType
    step_time: TimeType
    ramp_time: TimeType | None = None
    end_temperature: TemperatureType | None = None


class MashProcedureType(_BJ):
    name: str | None = None  # required by schema; recipes rarely name the whole procedure
    grain_temperature: TemperatureType | None = None  # required by schema; rarely stated
    mash_steps: list[MashStepType] = Field(min_length=1)


class BoilStepType(_BJ):
    name: str | None = Field(
        default=None, min_length=1, max_length=80
    )  # required by schema; often unstated, see module docstring
    description: str | None = Field(default=None, max_length=500)
    start_temperature: TemperatureType | None = None
    end_temperature: TemperatureType | None = None
    step_time: TimeType | None = None
    chilling_type: Literal["batch", "inline"] | None = None


class BoilProcedureType(_BJ):
    name: str | None = None
    pre_boil_size: VolumeType | None = None
    boil_time: TimeType
    boil_steps: list[BoilStepType] | None = Field(default=None, max_length=2)


class FermentationStepType(_BJ):
    name: str = Field(min_length=1, max_length=80)
    start_temperature: TemperatureType | None = None
    end_temperature: TemperatureType | None = None
    step_time: TimeType | None = None
    free_rise: bool | None = None


class FermentationProcedureType(_BJ):
    name: str | None = None  # required by schema; recipes rarely name the whole procedure
    fermentation_steps: list[FermentationStepType] = Field(min_length=1)


class StyleType(_BJ):
    name: str = Field(min_length=1, max_length=150)
    category: str | None = None  # required by schema; often unstated
    style_guide: str | None = None  # required by schema; often unstated
    type: Literal["beer", "cider", "kombucha", "mead", "other", "soda", "wine"] | None = (
        None  # required by schema; often unstated
    )


class EfficiencyType(_BJ):
    brewhouse: PercentType


class RecipeModel(_BJ):
    """Subset of BeerJSON RecipeType. This is the wizard's canonical recipe."""

    name: str = Field(min_length=1, max_length=100)
    type: Literal[
        "all grain",
        "partial mash",
        "extract",
        "cider",
        "kombucha",
        "mead",
        "other",
        "soda",
        "wine",
    ] = "all grain"
    author: str | None = None
    style: StyleType | None = None
    batch_size: VolumeType | None = None
    efficiency: EfficiencyType | None = None
    original_gravity: GravityType | None = None
    final_gravity: GravityType | None = None
    alcohol_by_volume: PercentType | None = None
    color_estimate: ColorType | None = None
    notes: str = Field(min_length=12, max_length=2000)
    ingredients: IngredientsType
    mash: MashProcedureType | None = None
    boil: BoilProcedureType | None = None
    fermentation: FermentationProcedureType | None = None

    @model_validator(mode="after")
    def boil_steps_follow_convention(self) -> Self:
        steps = (self.boil.boil_steps if self.boil else None) or []
        if len(steps) == 2 and steps[1].step_time is None:
            raise ValueError("whirlpool boil step requires step_time")
        return self


_EXPORT_DEFAULTS = {
    "author": lambda: "Unknown",
    "type": lambda: "all grain",
    "batch_size": lambda: {"unit": "l", "value": 20},
    "efficiency": lambda: {"brewhouse": {"unit": "%", "value": 70}},
}
_UNKNOWN_CULTURE_TYPE = "other"
_UNKNOWN_CULTURE_FORM = "culture"
_UNKNOWN_MISC_TYPE = "other"
_DEFAULT_MASH_NAME = "Mash"
_DEFAULT_FERMENTATION_NAME = "Fermentation"
_DEFAULT_STYLE_CATEGORY = "Unknown"
_DEFAULT_STYLE_GUIDE = "Unknown"
_DEFAULT_STYLE_TYPE = "beer"
_DEFAULT_BOIL_STEP_NAMES = ("Boil", "Whirlpool")


def _unknown_alpha_acid() -> dict:
    return {"unit": "%", "value": 0}


def _unknown_color() -> dict:
    return {"unit": "SRM", "value": 0}


def _unknown_yield() -> dict:
    return {"fine_grind": {"unit": "%", "value": 0}}


def _default_grain_temperature() -> dict:
    return {"unit": "C", "value": 20}


def _step_placeholder_name(step: dict) -> str:
    temperature = step.get("step_temperature")
    return f"{temperature['value']:g} °{temperature['unit']}" if temperature else "Rest"


def to_beerjson_document(recipe: RecipeModel) -> dict:
    """Wrap the recipe in a full BeerJSON document, filling schema-required fields
    that the wizard legitimately may not know. Placeholders are export-only; the
    internal model keeps them absent."""
    data = recipe.model_dump(by_alias=True, exclude_none=True)
    for key, factory in _EXPORT_DEFAULTS.items():
        if key not in data:
            data[key] = factory()

    style = data.get("style")
    if style is not None:
        style.setdefault("category", _DEFAULT_STYLE_CATEGORY)
        style.setdefault("style_guide", _DEFAULT_STYLE_GUIDE)
        style.setdefault("type", _DEFAULT_STYLE_TYPE)

    mash = data.get("mash")
    if mash is not None:
        mash.setdefault("name", _DEFAULT_MASH_NAME)
        if "grain_temperature" not in mash:
            mash["grain_temperature"] = _default_grain_temperature()
        for step in mash.get("mash_steps") or []:
            step.setdefault("name", _step_placeholder_name(step))

    for index, step in enumerate((data.get("boil") or {}).get("boil_steps") or []):
        step.setdefault("name", _DEFAULT_BOIL_STEP_NAMES[index])

    fermentation = data.get("fermentation")
    if fermentation is not None:
        fermentation.setdefault("name", _DEFAULT_FERMENTATION_NAME)

    for fermentable in data["ingredients"]["fermentable_additions"]:
        if "color" not in fermentable:
            fermentable["color"] = _unknown_color()
        if "yield" not in fermentable:
            fermentable["yield"] = _unknown_yield()

    for hop in data["ingredients"].get("hop_additions") or []:
        hop.setdefault("timing", {})  # required by schema; TimingType has no required props
        if "alpha_acid" not in hop:
            hop["alpha_acid"] = _unknown_alpha_acid()

    for culture in data["ingredients"].get("culture_additions") or []:
        culture.setdefault("type", _UNKNOWN_CULTURE_TYPE)
        culture.setdefault("form", _UNKNOWN_CULTURE_FORM)

    for misc in data["ingredients"].get("miscellaneous_additions") or []:
        misc.setdefault("type", _UNKNOWN_MISC_TYPE)

    return {"beerjson": {"version": 1, "recipes": [data]}}
