"""CLI wrapper. Usage (from backend/): uv run python scripts/sync_yeasts.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from features.yeasts.services import sync_yeasts

if __name__ == "__main__":
    count = sync_yeasts()
    print(f"synced {count} yeasts")
