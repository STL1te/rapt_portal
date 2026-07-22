"""Local recipe (profile) library: read, edit locally, upload to RAPT."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from core.db import Profile, SessionLocal
from features.system.services import start_profile_upload_job

from .enums import PROFILE_TYPE_OPTIONS
from .services import create_profile, delete_profile, profile_dict, update_profile

router = APIRouter()


class AlertIn(BaseModel):
    id: str | None = None
    alertText: str | None = None
    trigger: str | None = None
    operator: str | None = None
    temperature: float | None = None
    gravity: float | None = None
    length: int | None = None  # step-level alerts only (trigger=Duration); RAPT Int32


class StepIn(BaseModel):
    id: str | None = None
    name: str | None = None
    order: int = 0
    controlType: str | None = None
    endType: str | None = None
    durationType: str | None = None
    operator: str | None = None
    length: int | None = None  # seconds; RAPT Int32
    temperature: float | None = None
    minTemperature: float | None = None
    maxTemperature: float | None = None
    gravity: float | None = None
    pumpEnabled: bool | None = None
    pumpUtilisation: float | None = None
    heatingUtilisation: float | None = None
    pidEnabled: bool | None = None
    sensorDifferential: float | None = None
    alerts: list[AlertIn] = []


class ProfileIn(BaseModel):
    name: str
    description: str | None = None
    public: bool = False
    profile_type_id: str | None = None
    profile_type_name: str | None = None
    steps: list[StepIn] = []
    alerts: list[AlertIn] = []


class UploadRequest(BaseModel):
    portal_token: str


@router.get("/api/profiles")
def list_profiles(type_id: str | None = None) -> list[dict]:
    with SessionLocal() as db:
        stmt = select(Profile).where(Profile.archived.is_(False))
        if type_id:
            stmt = stmt.where(Profile.profile_type_id == type_id)
        stmt = stmt.order_by(Profile.name)
        return [profile_dict(p, include_steps=False) for p in db.scalars(stmt)]


@router.get("/api/profile-types")
def profile_types() -> list[dict]:
    """RAPT's account-global profile types — for the editor's type picker."""
    return list(PROFILE_TYPE_OPTIONS)


@router.get("/api/profiles/{profile_id}")
def get_profile(profile_id: str) -> dict:
    with SessionLocal() as db:
        p = db.get(Profile, profile_id)
        if not p:
            raise HTTPException(404, "profile not found")
        return profile_dict(p)


@router.post("/api/profiles", status_code=status.HTTP_201_CREATED)
def post_profile(payload: ProfileIn) -> dict:
    return create_profile(payload.model_dump())


@router.put("/api/profiles/{profile_id}")
def put_profile(profile_id: str, payload: ProfileIn) -> dict:
    updated = update_profile(profile_id, payload.model_dump())
    if updated is None:
        raise HTTPException(404, "profile not found")
    return updated


@router.delete("/api/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def del_profile(profile_id: str) -> None:
    if not delete_profile(profile_id):
        raise HTTPException(404, "profile not found")


@router.post("/api/profiles/{profile_id}/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload(profile_id: str, payload: UploadRequest) -> dict:
    return await start_profile_upload_job(profile_id, payload.portal_token)
