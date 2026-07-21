"""Health check and manual sync trigger."""

from fastapi import APIRouter
from pydantic import BaseModel

import sync
from scripts.portal_data_sync import portal_data_sync
from scripts.sync_yeasts import sync_yeasts

router = APIRouter()


class PortalTokenRequest(BaseModel):
    portal_token: str


class PortalSyncRequest(PortalTokenRequest):
    force: bool = False


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.post("/sync")
async def trigger_sync() -> dict:
    return await sync.sync_once()


@router.post("/portal_data_sync")
async def trigger_portal_data_sync(payload: PortalSyncRequest) -> dict:
    await portal_data_sync(force=payload.force, portal_token=payload.portal_token)
    return {"status": "ok"}


@router.post("/sync_yeasts")
def trigger_sync_yeasts(payload: PortalTokenRequest) -> dict:
    count = sync_yeasts(portal_token=payload.portal_token)
    return {"status": "ok", "count": count}
