"""Thin async RAPT API client with in-memory token cache."""

import asyncio
import time

import httpx

from core.config import API_BASE, RAPT_SECRET, RAPT_USERNAME, TOKEN_URL

_token: str | None = None
_token_expiry: float = 0.0  # unix seconds


async def get_token() -> str:
    """Return a valid bearer token, refreshing 60s before it expires."""
    global _token, _token_expiry
    if _token and time.time() < _token_expiry - 60:
        return _token

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "client_id": "rapt-user",
                "grant_type": "password",
                "username": RAPT_USERNAME,
                "password": RAPT_SECRET,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        data = resp.json()

    _token = data["access_token"]
    _token_expiry = time.time() + data.get("expires_in", 3600)
    return _token


async def get(path: str, params: dict | None = None) -> object:
    """GET a RAPT API path, retrying on 429 (honors Retry-After)."""
    token = await get_token()
    async with httpx.AsyncClient(timeout=30) as client:
        for attempt in range(5):
            resp = await client.get(
                f"{API_BASE}{path}",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code == 429:
                wait = float(resp.headers.get("Retry-After", 2**attempt))
                await asyncio.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()  # out of retries — surface the 429


async def get_hydrometers() -> list[dict]:
    return await get("/api/Hydrometers/GetHydrometers")


async def get_telemetry(
    hydrometer_id: str,
    start: str | None = None,
    end: str | None = None,
    session_id: str | None = None,
) -> list[dict]:
    params = {"hydrometerId": hydrometer_id}
    if start:
        params["startDate"] = start
    if end:
        params["endDate"] = end
    if session_id:
        params["profileSessionId"] = session_id
    return await get("/api/Hydrometers/GetTelemetry", params)


async def get_brewzillas() -> list[dict]:
    return await get("/api/BrewZillas/GetBrewZillas")


async def get_brewzilla_telemetry(
    brewzilla_id: str, start: str | None = None, session_id: str | None = None
) -> list[dict]:
    params = {"brewZillaId": brewzilla_id}
    if start:
        params["startDate"] = start
    if session_id:
        params["profileSessionId"] = session_id
    return await get("/api/BrewZillas/GetTelemetry", params)


async def demo() -> None:
    """Sanity check: log in and dump the first hydrometer's raw JSON."""
    import json

    hydrometers = await get_hydrometers()
    print(f"token OK, {len(hydrometers)} hydrometer(s)")
    if hydrometers:
        print(json.dumps(hydrometers[0], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    import asyncio

    asyncio.run(demo())
