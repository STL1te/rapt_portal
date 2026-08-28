"""Facade: turn a recipe from any supported source into the canonical RecipeModel, so
every caller feeds brewzilla_compiler.compile_brewzilla_profile the same way regardless
of where the recipe came from — AI wizard extraction, BrewFather JSON, BeerXML, or
BeerJSON."""

import json
from typing import Literal

from .beerjson import parse_beerjson
from .beerjson_models import RecipeModel
from .beerxml import parse_beerxml
from .brewfather import parse_brewfather_json

RecipeSourceFormat = Literal["brewfather_json", "beerxml", "beerjson"]


def _load_object(raw: str) -> dict:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON: {error}") from error
    if not isinstance(data, dict):
        raise ValueError("recipe JSON must be an object")
    return data


def import_recipe(source_format: RecipeSourceFormat, raw: str) -> RecipeModel:
    if source_format == "brewfather_json":
        return parse_brewfather_json(_load_object(raw))
    if source_format == "beerjson":
        return parse_beerjson(_load_object(raw))
    if source_format == "beerxml":
        return parse_beerxml(raw)
    raise ValueError(f"unsupported recipe format: {source_format}")
