"""Portal session metadata sync for profile-session history.

The public RAPT API exposes only the *active* session per hydrometer, so past
sessions come from the portal-only endpoint GetHydrometerProfileSessions, which
needs a `rapt-web` bearer token. Grab it from the browser: open the RAPT portal,
DevTools -> Network -> any request -> copy the `Authorization: Bearer ...` value
(valid ~60 min).

Default mode updates/creates portal sessions and fetches telemetry only for
newly discovered sessions. Use ``--force`` to re-run telemetry sync for every
session returned by the portal.

Usage (from backend/):
  PORTAL_TOKEN="eyJ..." uv run python -m scripts.portal_data_sync
  PORTAL_TOKEN="eyJ..." uv run python -m scripts.portal_data_sync --force
"""

import argparse
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


def _normalize_token(token: str | None) -> str:
    return (token or "").removeprefix("Bearer ").strip()


def _load_token(portal_token: str | None = None) -> str:
    tok = portal_token or os.environ.get("PORTAL_TOKEN", "")
    if not tok and os.path.exists(".portal_token"):
        with open(".portal_token", encoding="utf-8") as f:
            tok = f.read()
    return _normalize_token(tok)


def _safe_name(value: str | None) -> str:
    return ascii(value)[1:-1] if value else "unknown"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Sync portal session metadata into the local DB")
    p.add_argument(
        "--force",
        action="store_true",
        help="re-fetch telemetry for every portal session instead of only new ones",
    )
    return p.parse_args()


async def _list_sessions(
    client: httpx.AsyncClient, token: str, endpoint: str, id_param: str, id_value: str
) -> list[dict]:
    out: list[dict] = []
    page = 1
    while True:
        r = await client.get(
            f"{API_BASE}/api/ProfileSessions/{endpoint}",
            params={id_param: id_value, "page": page, "pageSize": 100, "filterText": ""},
            headers={"Authorization": f"Bearer {token}"},
        )
        r.raise_for_status()
        data = r.json()
        out.extend(data["list"])
        if not data["list"] or len(out) >= data["totalCount"]:
            return out
        page += 1


def _is_new(db, model, row_id: str) -> bool:
    return db.get(model, row_id) is None


async def portal_data_sync(force: bool = False, portal_token: str | None = None) -> None:
    token = _load_token(portal_token)
    if not token:
        raise SystemExit("Set PORTAL_TOKEN to a portal (rapt-web) bearer token")

    init_db(finalize_stale=False)
    print("base sync:", await sync.sync_once())

    hydrometers = await rapt_client.get_hydrometers()

    async with httpx.AsyncClient(timeout=60) as client:
        for h in hydrometers:
            hid = h["id"]
            sessions = await _list_sessions(
                client, token, "GetHydrometerProfileSessions", "hydrometerId", hid
            )
            print(f"{_safe_name(h.get('name'))}: {len(sessions)} session(s)")
            for s in sessions:
                sid = s["id"]
                end = sync._dt(s.get("endDate"))
                with SessionLocal() as db:
                    is_new = _is_new(db, HydrometerSession, sid)
                    sync._upsert(
                        db,
                        HydrometerSession,
                        {
                            "id": sid,
                            "hydrometer_id": hid,
                            "name": s.get("name"),
                            "yeast_id": s.get("yeastId"),
                            "start_date": sync._dt(s.get("startDate")),
                            "end_date": end,
                            "active": end is None,
                        },
                    )
                    db.commit()
                if is_new or force:
                    await sync._sync_telemetry(hid, sid)
                    sync._refresh_gravities(sid)
                await asyncio.sleep(0.5)

        await _sync_brewzillas(client, token, force=force)

    with SessionLocal() as db:
        print(
            "DB totals -> hydro sessions:",
            db.scalar(select(func.count(HydrometerSession.id))),
            "| hydro telemetry:",
            db.scalar(select(func.count(HydrometerTelemetry.id))),
            "| brew sessions:",
            db.scalar(select(func.count(BrewSession.id))),
            "| brew telemetry:",
            db.scalar(select(func.count(BrewTelemetry.id))),
        )


async def _sync_brewzillas(client: httpx.AsyncClient, token: str, force: bool = False) -> None:
    import json

    for b in await rapt_client.get_brewzillas():
        bid = b["id"]
        sessions = await _list_sessions(
            client, token, "GetBrewZillaProfileSessions", "brewZillaId", bid
        )
        print(f"{_safe_name(b.get('name'))}: {len(sessions)} brew session(s)")
        for s in sessions:
            sid = s["id"]
            end = sync._dt(s.get("endDate"))
            prof = s.get("profile")
            with SessionLocal() as db:
                is_new = _is_new(db, BrewSession, sid)
                sync._upsert(
                    db,
                    BrewSession,
                    {
                        "id": sid,
                        "brewzilla_id": bid,
                        "name": (prof or {}).get("name"),
                        "profile_id": s.get("profileId"),
                        "profile_json": json.dumps(prof, ensure_ascii=False) if prof else None,
                        "start_date": sync._dt(s.get("startDate")),
                        "end_date": end,
                        "active": end is None,
                    },
                )
                db.commit()
            if is_new or force:
                await sync._sync_brew_telemetry(bid, sid)
            await asyncio.sleep(0.5)


def main() -> None:
    args = _parse_args()
    asyncio.run(portal_data_sync(force=args.force))


if __name__ == "__main__":
    main()
