"""Sync the yeast catalog from the RAPT portal inventory."""

import httpx
from sqlalchemy import select

from core import rapt_auth, sync
from core.config import API_BASE
from core.db import SessionLocal, Yeast


def sync_yeasts() -> int:
    token = rapt_auth.portal_token()

    headers = {"Authorization": f"Bearer {token}"}
    page = 1
    total = 0
    seen_ids: set[str] = set()

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
                    seen_ids.add(item["id"])
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

    with SessionLocal() as db:
        for yeast in db.scalars(select(Yeast)):
            yeast.archived = yeast.id not in seen_ids
        db.commit()

    return total
