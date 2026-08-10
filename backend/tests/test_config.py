import pytest

from core.config import _parse_extra_body


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("", {}),
        ('{"reasoning_effort":"none"}', {"reasoning_effort": "none"}),
        # CasaOS strips quotes from env values, so the JSON form is untypeable there
        ("reasoning_effort=none", {"reasoning_effort": "none"}),
        ("reasoning_effort=none,think=false", {"reasoning_effort": "none", "think": "false"}),
    ],
)
def test_parse_extra_body(raw, expected):
    assert _parse_extra_body(raw) == expected
