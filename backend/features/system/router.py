"""Health check, RAPT OAuth login and manual sync triggers."""

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from core import rapt_auth

from .services import (
    get_job,
    list_active_jobs,
    list_job_history,
    start_base_sync_job,
    start_portal_sync_job,
    start_profile_sync_job,
    start_yeast_sync_job,
)

router = APIRouter()


class PortalSyncRequest(BaseModel):
    force: bool = False


class RaptAuthRequest(BaseModel):
    # the whole https://app.rapt.io/callback?code=... URL, or just the code
    code: str


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/api/rapt_auth")
def rapt_auth_status() -> dict:
    return {"connected": rapt_auth.is_connected()}


@router.get("/api/rapt_auth/url")
def rapt_auth_url() -> dict:
    return {"url": rapt_auth.login_url()}


@router.post("/api/rapt_auth")
def rapt_auth_connect(payload: RaptAuthRequest) -> dict:
    try:
        rapt_auth.complete(payload.code)
    except (ValueError, RuntimeError) as error:
        raise HTTPException(400, str(error)) from error
    return {"connected": True}


@router.post("/api/sync", status_code=status.HTTP_202_ACCEPTED)
async def trigger_sync() -> dict:
    return await start_base_sync_job()


@router.post("/api/portal_data_sync", status_code=status.HTTP_202_ACCEPTED)
async def trigger_portal_data_sync(payload: PortalSyncRequest) -> dict:
    return await start_portal_sync_job(payload.force)


@router.post("/api/sync_yeasts", status_code=status.HTTP_202_ACCEPTED)
async def trigger_sync_yeasts() -> dict:
    return await start_yeast_sync_job()


@router.post("/api/sync_profiles", status_code=status.HTTP_202_ACCEPTED)
async def trigger_sync_profiles() -> dict:
    return await start_profile_sync_job()


@router.get("/api/system-jobs")
def system_jobs() -> list[dict]:
    return list_active_jobs()


@router.get("/api/system-jobs/history")
def system_job_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    return list_job_history(page, page_size)


@router.get("/api/system-jobs/{job_id}")
def system_job(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job
