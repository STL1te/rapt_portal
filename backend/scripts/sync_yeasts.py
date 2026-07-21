"""Sync the yeast catalog from the RAPT portal inventory.

Usage (from backend/):
  uv run python scripts/sync_yeasts.py
"""

import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sync
from config import API_BASE
from db import SessionLocal, Yeast, init_db


def _load_token() -> str:
    tok = os.environ.get("PORTAL_TOKEN", "")
    if not tok and Path(".portal_token").exists():
        tok = Path(".portal_token").read_text(encoding="utf-8")
    return tok.removeprefix("Bearer ").strip()


def sync_yeasts(portal_token: str | None = None) -> int:
    token = (portal_token or _load_token()).removeprefix("Bearer ").strip()
    if not token:
        raise SystemExit("Set PORTAL_TOKEN to a portal bearer token")

    init_db()
    headers = {"Authorization": f"Bearer {token}"}
    page = 1
    total = 0

    with httpx.Client(timeout=60) as client:
        while True:
            resp = client.get(
                f"{API_BASE}/api/Inventory/Yeasts/GetAll",
                params={
                    "pageSize": 100,
                    "page": page,
                    "textFilter": "",
                    "includeMyInventory": "false",
                    "includeGlobal": "true",
                    "archived": "false",
                },
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("list") or []
            if not items:
                break

            with SessionLocal() as db:
                for item in items:
                    sync._upsert(
                        db,
                        Yeast,
                        {
                            "id": item["id"],
                            "name": item.get("name"),
                            "product_id": item.get("productId"),
                            "laboratory": item.get("laboratory"),
                            "type": item.get("type"),
                            "form": item.get("form"),
                            "min_temperature": item.get("minTemperature"),
                            "max_temperature": item.get("maxTemperature"),
                            "flocculation": item.get("flocculation"),
                            "attenuation": item.get("attenuation"),
                            "notes": item.get("notes"),
                            "is_global": bool(item.get("isGlobal")),
                            "archived": bool(item.get("archived")),
                        },
                    )
                db.commit()

            total += len(items)
            if total >= data.get("totalCount", total):
                break
            page += 1

    return total


if __name__ == "__main__":
    count = sync_yeasts()
    print(f"synced {count} yeasts")
