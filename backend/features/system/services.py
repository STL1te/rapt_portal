"""DB-backed background jobs for long-running system syncs."""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from core import sync
from core.db import SessionLocal, SystemJob
from features.profiles.services import sync_profiles, upload_profile
from features.yeasts.services import sync_yeasts
from .portal_sync import portal_data_sync

TERMINAL_STATUSES = {"done", "failed"}
ACTIVE_STATUSES = {"queued", "running"}

_start_locks = {
    "base_sync": asyncio.Lock(),
    "portal_sync": asyncio.Lock(),
    "yeast_sync": asyncio.Lock(),
    "profile_sync": asyncio.Lock(),
    "profile_upload": asyncio.Lock(),
}
_run_locks = {
    "base_sync": asyncio.Lock(),
    "portal_sync": asyncio.Lock(),
    "yeast_sync": asyncio.Lock(),
    "profile_sync": asyncio.Lock(),
    "profile_upload": asyncio.Lock(),
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def _snapshot(job: SystemJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "created_at": _stamp(job.created_at),
        "started_at": _stamp(job.started_at),
        "finished_at": _stamp(job.finished_at),
        "result": json.loads(job.result_json) if job.result_json else None,
        "error": job.error,
    }


def get_job(job_id: str) -> dict[str, Any] | None:
    with SessionLocal() as db:
        job = db.get(SystemJob, job_id)
        return _snapshot(job) if job else None


def list_active_jobs() -> list[dict[str, Any]]:
    with SessionLocal() as db:
        jobs = (
            db.query(SystemJob)
            .filter(SystemJob.status.in_(ACTIVE_STATUSES))
            .order_by(SystemJob.created_at.asc())
            .all()
        )
        return [_snapshot(job) for job in jobs]


def list_job_history(page: int, page_size: int) -> dict[str, Any]:
    offset = (page - 1) * page_size
    with SessionLocal() as db:
        total = db.query(SystemJob).count()
        jobs = (
            db.query(SystemJob)
            .order_by(SystemJob.created_at.desc())
            .offset(offset)
            .limit(page_size)
            .all()
        )
        return {
            "items": [_snapshot(job) for job in jobs],
            "page": page,
            "page_size": page_size,
            "total": total,
        }


def finalize_stale_jobs() -> int:
    with SessionLocal() as db:
        jobs = db.query(SystemJob).filter(SystemJob.status.in_(ACTIVE_STATUSES)).all()
        if not jobs:
            return 0

        finished_at = _utcnow()
        for job in jobs:
            job.status = "failed"
            job.finished_at = finished_at
            job.error = "Interrupted by application restart"
            if job.started_at is None:
                job.started_at = finished_at
        db.commit()
        return len(jobs)


async def ensure_interval_base_sync() -> None:
    job = await start_base_sync_job()
    if job["status"] in TERMINAL_STATUSES:
        return


async def start_base_sync_job() -> dict[str, Any]:
    return await _start_job("base_sync", run_base_sync)


async def start_portal_sync_job(portal_token: str, force: bool) -> dict[str, Any]:
    async def runner() -> dict[str, Any]:
        async with _run_locks["portal_sync"]:
            async with _run_locks["base_sync"]:
                await portal_data_sync(force=force, portal_token=portal_token)
        return {"status": "ok"}

    return await _start_job("portal_sync", runner)


async def start_yeast_sync_job(portal_token: str) -> dict[str, Any]:
    async def runner() -> dict[str, Any]:
        async with _run_locks["yeast_sync"]:
            count = await asyncio.to_thread(sync_yeasts, portal_token)
        return {"status": "ok", "count": count}

    return await _start_job("yeast_sync", runner)


async def start_profile_sync_job(portal_token: str) -> dict[str, Any]:
    async def runner() -> dict[str, Any]:
        async with _run_locks["profile_sync"]:
            count = await asyncio.to_thread(sync_profiles, portal_token)
        return {"status": "ok", "count": count}

    return await _start_job("profile_sync", runner)


async def start_profile_upload_job(profile_id: str, portal_token: str) -> dict[str, Any]:
    async def runner() -> dict[str, Any]:
        async with _run_locks["profile_upload"]:
            # resync inside upload_profile also touches profiles, so hold that lock too
            async with _run_locks["profile_sync"]:
                return await asyncio.to_thread(upload_profile, profile_id, portal_token)

    return await _start_job("profile_upload", runner)


async def run_base_sync() -> dict[str, Any]:
    async with _run_locks["base_sync"]:
        return await sync.sync_once()


async def _start_job(
    kind: str,
    runner: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    async with _start_locks[kind]:
        with SessionLocal() as db:
            active = (
                db.query(SystemJob)
                .filter(
                    SystemJob.kind == kind,
                    SystemJob.status.in_(ACTIVE_STATUSES),
                )
                .order_by(SystemJob.created_at.desc())
                .first()
            )
            if active:
                return _snapshot(active)

            job = SystemJob(
                id=uuid.uuid4().hex,
                kind=kind,
                status="queued",
                created_at=_utcnow(),
            )
            db.add(job)
            db.commit()
            snapshot = _snapshot(job)

        asyncio.create_task(_run_job(snapshot["id"], runner))
        return snapshot


async def _run_job(
    job_id: str,
    runner: Callable[[], Awaitable[dict[str, Any]]],
) -> None:
    with SessionLocal() as db:
        job = db.get(SystemJob, job_id)
        if not job:
            return
        job.status = "running"
        job.started_at = _utcnow()
        db.commit()

    try:
        result = await runner()
        status = "done"
        error = None
    except Exception as exc:  # noqa: BLE001
        result = None
        status = "failed"
        error = str(exc)

    with SessionLocal() as db:
        job = db.get(SystemJob, job_id)
        if not job:
            return
        job.status = status
        job.finished_at = _utcnow()
        job.result_json = json.dumps(result, ensure_ascii=False) if result is not None else None
        job.error = error
        db.commit()
