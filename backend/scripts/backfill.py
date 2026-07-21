"""One-off backfill of full profile-session history from a fresh DB.

The public RAPT API exposes only the *active* session per hydrometer, so past
sessions come from the portal-only endpoint GetHydrometerProfileSessions, which
needs a `rapt-web` bearer token. Grab it from the browser: open the RAPT portal,
DevTools -> Network -> any request -> copy the `Authorization: Bearer ...` value
(valid ~60 min). Telemetry itself is fetched with the normal api-secret token.

Sessions carry no endDate/OG/FG even here, so OG/FG are derived from the
first/last telemetry point and end_date from the last point.

Usage (from backend/):
  PORTAL_TOKEN="eyJ..." uv run python -m scripts.backfill
"""
import asyncio
import os

import httpx
from sqlalchemy import func, select

import rapt_client
import sync
from config import API_BASE
from db import (
    BrewSession,
    BrewTelemetry,
    HydrometerSession,
    HydrometerTelemetry,
    SessionLocal,
    init_db,
)

def _load_token() -> str:
    tok = os.environ.get("PORTAL_TOKEN", "")
    if not tok and os.path.exists(".portal_token"):
        with open(".portal_token", encoding="utf-8") as f:
            tok = f.read()
    return tok.removeprefix("Bearer ").strip()


PORTAL_TOKEN = _load_token()


async def _list_sessions(
    client: httpx.AsyncClient, endpoint: str, id_param: str, id_value: str
) -> list[dict]:
    """All profile sessions for a device (portal endpoint), following pagination."""
    out: list[dict] = []
    page = 1
    while True:
        r = await client.get(
            f"{API_BASE}/api/ProfileSessions/{endpoint}",
            params={id_param: id_value, "page": page, "pageSize": 100, "filterText": ""},
            headers={"Authorization": f"Bearer {PORTAL_TOKEN}"},
        )
        r.raise_for_status()
        data = r.json()
        out.extend(data["list"])
        if not data["list"] or len(out) >= data["totalCount"]:
            return out
        page += 1


async def backfill() -> None:
    if not PORTAL_TOKEN:
        raise SystemExit("Set PORTAL_TOKEN to a portal (rapt-web) bearer token")

    init_db()
    # hydrometers + active sessions + their telemetry (via api-secret)
    print("base sync:", await sync.sync_once())

    hydrometers = await rapt_client.get_hydrometers()

    async with httpx.AsyncClient(timeout=60) as client:
        for h in hydrometers:
            hid = h["id"]
            sessions = await _list_sessions(
                client, "GetHydrometerProfileSessions", "hydrometerId", hid)
            print(f"{h['name']}: {len(sessions)} session(s)")
            for s in sessions:
                sid = s["id"]
                end = sync._dt(s.get("endDate"))  # absent (null) => still active
                with SessionLocal() as db:
                    sync._upsert(db, HydrometerSession, {
                        "id": sid,
                        "hydrometer_id": hid,
                        "name": s.get("name"),
                        "start_date": sync._dt(s.get("startDate")),
                        "end_date": end,
                        "active": end is None,
                    })
                    db.commit()
                await sync._sync_telemetry(hid, sid)
                sync._refresh_gravities(sid)  # OG/FG genuinely not in payload
                await asyncio.sleep(0.5)  # be gentle with RAPT's rate limiter

        await _backfill_brewzillas(client)

    with SessionLocal() as db:
        print("DB totals -> hydro sessions:", db.scalar(select(func.count(HydrometerSession.id))),
              "| hydro telemetry:", db.scalar(select(func.count(HydrometerTelemetry.id))),
              "| brew sessions:", db.scalar(select(func.count(BrewSession.id))),
              "| brew telemetry:", db.scalar(select(func.count(BrewTelemetry.id))))


async def _backfill_brewzillas(client: httpx.AsyncClient) -> None:
    import json

    for b in await rapt_client.get_brewzillas():
        bid = b["id"]
        sessions = await _list_sessions(
            client, "GetBrewZillaProfileSessions", "brewZillaId", bid)
        print(f"{b['name']}: {len(sessions)} brew session(s)")
        for s in sessions:
            sid = s["id"]
            end = sync._dt(s.get("endDate"))  # absent (null) => still active
            prof = s.get("profile")
            with SessionLocal() as db:
                sync._upsert(db, BrewSession, {
                    "id": sid,
                    "brewzilla_id": bid,
                    "name": (prof or {}).get("name"),
                    "profile_id": s.get("profileId"),
                    "profile_json": json.dumps(prof, ensure_ascii=False) if prof else None,
                    "start_date": sync._dt(s.get("startDate")),
                    "end_date": end,
                    "active": end is None,
                })
                db.commit()
            await sync._sync_brew_telemetry(bid, sid)
            await asyncio.sleep(0.5)  # be gentle with RAPT's rate limiter


if __name__ == "__main__":
    asyncio.run(backfill())
