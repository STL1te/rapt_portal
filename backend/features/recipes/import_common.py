"""Shared enum mapping and timing helpers for third-party recipe importers (BrewFather
JSON, BeerXML). Both formats describe ingredient additions with a source-specific
"use" label (Boil/Aroma/Dry Hop/Mash/...); this maps that label to the BeerJSON
`TimingType` convention the compiler expects (docs/beerjson-migration-plan.md 3.1-3.2).
"""

from .beerjson_models import TimeType, TimingType

_FERMENTABLE_TYPES = {"grain", "extract", "dry extract", "sugar", "fruit", "juice", "honey"}
_MISC_TYPES = {"spice", "fining", "water agent", "herb", "flavor", "wood"}
_CULTURE_TYPES = {
    "ale",
    "lager",
    "wine",
    "champagne",
    "kveik",
    "bacteria",
    "brett",
    "lacto",
    "pedio",
    "spontaneous",
    "malolactic",
    "mixed-culture",
}
_CULTURE_FORMS = {"liquid", "dry", "slant", "culture"}
_HOP_FORMS = {
    "pellet": "pellet",
    "leaf": "leaf",
    "leaf (wet)": "leaf (wet)",
    "plug": "plug",
    "powder": "powder",
    "lupulin powder": "powder",
    "extract": "extract",
    "co2 extract": "extract",
    "cryo": "powder",
}
_RECIPE_TYPES = {
    "all grain": "all grain",
    "biab": "all grain",
    "extract": "extract",
    "partial mash": "partial mash",
}

_BOIL_USES = {"boil"}
_FIRST_WORT_USES = {"first wort"}
_WHIRLPOOL_USES = {"aroma", "whirlpool", "hopstand", "flameout", "flame out", "steep"}
_MASH_USES = {"mash"}
_FERMENTATION_USES = {"dry hop", "primary", "secondary", "fermentation"}


def clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def lower(value: object) -> str | None:
    text = clean_text(value)
    return text.lower() if text else None


def named(raw: object, fallback: str) -> str:
    """Name an addition that the source left unnamed.

    Both exporters happily write a row with an amount and a timing but no name — an
    addition typed straight into the recipe without picking a variety from the
    catalogue. Such a row is still a real addition (it drives a boil alert), so it
    keeps its amount and timing and gets a generic name rather than being dropped.
    """
    return clean_text(raw) or fallback


def recipe_type(raw: object) -> str:
    return _RECIPE_TYPES.get(lower(raw) or "", "all grain")


def fermentable_type(raw: object) -> str:
    value = lower(raw)
    return value if value in _FERMENTABLE_TYPES else "other"


def misc_type(raw: object) -> str | None:
    value = lower(raw)
    return value if value in _MISC_TYPES else None


def culture_type(raw: object) -> str | None:
    value = lower(raw)
    return value if value in _CULTURE_TYPES else None


def culture_form(raw: object) -> str | None:
    value = lower(raw)
    return value if value in _CULTURE_FORMS else None


def hop_form(raw: object) -> str | None:
    return _HOP_FORMS.get(lower(raw) or "")


def ingredient_timing(
    use: str | None,
    time: float | None,
    time_unit: str,
    boil_time_min: float | None,
) -> TimingType | None:
    normalized = lower(use)
    if normalized in _BOIL_USES and time is not None:
        return TimingType(use="add_to_boil", duration=TimeType(unit=time_unit, value=time))
    if normalized in _FIRST_WORT_USES and boil_time_min is not None:
        return TimingType(use="add_to_boil", duration=TimeType(unit="min", value=boil_time_min))
    if normalized in _WHIRLPOOL_USES and time is not None and boil_time_min is not None:
        return TimingType(
            use="add_to_boil",
            time=TimeType(unit="min", value=boil_time_min),
            duration=TimeType(unit=time_unit, value=time),
        )
    if normalized in _FERMENTATION_USES and time is not None:
        return TimingType(use="add_to_fermentation", duration=TimeType(unit=time_unit, value=time))
    if normalized in _MASH_USES:
        return TimingType(use="add_to_mash")
    return None


def is_whirlpool_use(use: str | None) -> bool:
    return lower(use) in _WHIRLPOOL_USES
