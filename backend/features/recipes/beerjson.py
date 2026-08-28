"""BeerJSON 1.0 document -> RecipeModel.

Nearly a no-op: RecipeModel already *is* a subset of BeerJSON RecipeType, so importing
is validation rather than translation. Two adjustments are still needed.

1. Our models are `extra="forbid"` and cover 14 of RecipeType's 24 properties, so
   anything outside the subset (ibu_estimate, carbonation, packaging, taste, created,
   beer_pH, ...) is pruned before validation instead of being rejected. The same holds
   one level down (a hop carrying beta_acid/percent_lost, a mash step carrying end_ph).
2. The official mash step enum includes "sparge" and "drain mash tun", which are not
   mash rests. The compiler owns sparging through its own include_sparge toggle, so
   those steps are dropped rather than compiled into rests.
"""

import types
from typing import Union, get_args, get_origin

from pydantic import BaseModel

from .beerjson_models import RecipeModel

_NON_REST_MASH_STEPS = {"sparge", "drain mash tun"}


def _prune(value, annotation):
    """Drop object keys BeerJSON defines but our subset does not model."""
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        options = [a for a in get_args(annotation) if a is not type(None)]
        # `X | None` unwraps to X. A union of several models (amount: Mass|Volume|Unit)
        # is measurable units only — flat {unit, value} objects with nothing to prune.
        return _prune(value, options[0]) if len(options) == 1 else value
    if origin is list and isinstance(value, list):
        (item,) = get_args(annotation)
        return [_prune(v, item) for v in value]
    if (
        isinstance(annotation, type)
        and issubclass(annotation, BaseModel)
        and isinstance(value, dict)
    ):
        fields = {(f.alias or name): f for name, f in annotation.model_fields.items()}
        return {k: _prune(v, fields[k].annotation) for k, v in value.items() if k in fields}
    return value


def parse_beerjson(data: dict) -> RecipeModel:
    recipes = (data.get("beerjson") or data).get("recipes")
    if not isinstance(recipes, list) or not recipes:
        raise ValueError("BeerJSON document contains no recipes")

    recipe = _prune(recipes[0], RecipeModel)

    mash = recipe.get("mash")
    if isinstance(mash, dict):
        steps = [
            s for s in mash.get("mash_steps") or [] if s.get("type") not in _NON_REST_MASH_STEPS
        ]
        if steps:
            mash["mash_steps"] = steps
        else:
            recipe.pop("mash")

    return RecipeModel.model_validate(recipe)
