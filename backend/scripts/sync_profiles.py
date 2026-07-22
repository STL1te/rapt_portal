"""CLI wrapper. Usage (from backend/):
  PORTAL_TOKEN="eyJ..." uv run python scripts/sync_profiles.py
(or drop the token into backend/.portal_token)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from features.profiles.services import sync_profiles

if __name__ == "__main__":
    count = sync_profiles()
    print(f"synced {count} profiles")
