"""Health check and manual sync trigger."""

from fastapi import APIRouter

import sync

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.post("/sync")
async def trigger_sync() -> dict:
    return await sync.sync_once()
