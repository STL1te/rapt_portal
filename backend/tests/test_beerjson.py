"""Conformance harness: our BeerJSON output must validate against the vendored official schema."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from features.ai.beerjson_schema import assert_valid_beerjson

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
