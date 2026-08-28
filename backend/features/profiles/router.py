"""Local recipe (profile) library: read, edit locally, upload to RAPT."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from core.db import Profile, SessionLocal
from features.recipes.brewzilla_compiler import (
    compile_brewzilla_profile,
    rest_display_name,
    split_mash_out,
)
from features.recipes.brewzilla_overrides import BrewZillaOverrides, RestEndAlert
from features.recipes.importers import RecipeSourceFormat, import_recipe
from features.system.services import start_profile_upload_job

from .enums import PROFILE_TYPE_OPTIONS
from .schemas import AlertIn, ProfileIn, StepIn  # noqa: F401  (re-exported for callers)
from .services import create_profile, delete_profile, profile_dict, update_profile

router = APIRouter()


class UploadRequest(BaseModel):
    portal_token: str


class RecipeImportRequest(BaseModel):
    format: RecipeSourceFormat
    content: str = Field(min_length=1, max_length=2_000_000)
    overrides: BrewZillaOverrides | None = None
    # Raise an alert at the end of every mash rest, mash-out included. Only the server
    # knows how many rests a file has and what each is called, so it composes one text
    # per rest rather than taking a single text from the caller.
    rest_end_alerts: bool = False


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


def _rest_end_alert(label: str) -> str:
    """Name the rest in its own end-of-rest alert, so the device says which one ended.

    Exporters commonly name rests "Пауза 64 °C", where a "Пауза завершена: ..." prefix
    would stutter — such a label carries the sentence on its own.
    """
    return f"{label} завершена" if "пауза" in label.lower() else f"Пауза завершена: {label}"


@router.post("/api/profiles/import")
def import_profile(request: RecipeImportRequest) -> dict:
    """Compile a BrewFather JSON, BeerXML or BeerJSON recipe into an (unsaved) BrewZilla
    profile, the same shape the AI wizard returns — the editor persists it on save."""
    try:
        recipe = import_recipe(request.format, request.content)
        overrides = request.overrides or BrewZillaOverrides()
        if request.rest_end_alerts:
            rests, mash_out = split_mash_out(recipe)
            overrides = overrides.model_copy(
                update={
                    "rest_end_alerts": [
                        RestEndAlert(
                            rest_index=index, text=_rest_end_alert(rest_display_name(rest))
                        )
                        for index, rest in enumerate(rests)
                    ],
                    # The mash-out is a rest too, but the compiler takes its alert through
                    # a field of its own. Set it whether the mash-out was recognized in the
                    # file or will be added by default; the compiler ignores it when the
                    # mash-out is switched off.
                    "mash_out_end_alert_text": overrides.mash_out_end_alert_text
                    or _rest_end_alert(rest_display_name(mash_out) if mash_out else "Mash Out"),
                }
            )
        return compile_brewzilla_profile(recipe, overrides)
    except (ValueError, ValidationError) as error:
        raise HTTPException(422, str(error)) from error


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
