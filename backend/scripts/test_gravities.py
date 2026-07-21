"""Self-check for the OG/FG estimator. Run: uv run python scripts/test_gravities.py"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sync import _fg, _og


def test_normal_ferment():
    # OG ~1050 dropping to a ~1010 plateau
    g = [1050] * 10 + list(range(1050, 1010, -1)) + [1010] * 30
    assert abs(_og(g) - 1050) < 2
    assert abs(_fg(g) - 1010) < 2
    assert _fg(g) <= _og(g)


def test_pill_lifted_at_end():
    # finishes ~1012 then drifts far above OG when the Pill is pulled out
    g = [1046] * 10 + list(range(1046, 1012, -1)) + [1012] * 20 + [1120, 1180, 1150]
    assert _fg(g) <= _og(g)          # must not be fooled by the up-drift
    assert abs(_fg(g) - 1012) < 4    # lands on the real plateau, not the spike


def test_dry_cider_below_1000():
    # legitimately finishes below water
    g = [1052] * 10 + list(range(1052, 998, -1)) + [998] * 25
    assert abs(_fg(g) - 998) < 3


if __name__ == "__main__":
    test_normal_ferment()
    test_pill_lifted_at_end()
    test_dry_cider_below_1000()
    print("OK")
