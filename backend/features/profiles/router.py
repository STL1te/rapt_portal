"""Local recipe (profile) library synced from the RAPT profile API."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from core.db import Profile, SessionLocal

from .services import profile_dict

router = APIRouter()


@router.get("/api/profiles")
def list_profiles(type_id: str | None = None) -> list[dict]:
    with SessionLocal() as db:
        stmt = select(Profile).where(Profile.archived.is_(False))
        if type_id:
            stmt = stmt.where(Profile.profile_type_id == type_id)
        stmt = stmt.order_by(Profile.name)
        return [profile_dict(p, include_steps=False) for p in db.scalars(stmt)]


@router.get("/api/profiles/{profile_id}")
def get_profile(profile_id: str) -> dict:
    with SessionLocal() as db:
        p = db.get(Profile, profile_id)
        if not p:
            raise HTTPException(404, "profile not found")
        return profile_dict(p)
