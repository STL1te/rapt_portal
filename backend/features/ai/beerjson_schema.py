"""Validator against the vendored official BeerJSON schema."""

import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft7Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "vendor" / "beerjson"


@lru_cache(maxsize=1)
def beerjson_validator() -> Draft7Validator:
    resources = []
    for path in SCHEMA_DIR.glob("*.json"):
        contents = json.loads(path.read_text(encoding="utf-8"))
        resource = Resource.from_contents(contents, default_specification=DRAFT7)
        resources.append((path.name, resource))
        if "$id" in contents:
            resources.append((contents["$id"], resource))
    root = json.loads((SCHEMA_DIR / "beer.json").read_text(encoding="utf-8"))
    return Draft7Validator(root, registry=Registry().with_resources(resources))


def assert_valid_beerjson(document: dict) -> None:
    errors = sorted(beerjson_validator().iter_errors(document), key=str)
    if errors:
        details = "; ".join(
            f"{'/'.join(map(str, error.absolute_path))}: {error.message}" for error in errors[:10]
        )
        raise ValueError(f"document violates BeerJSON schema: {details}")
