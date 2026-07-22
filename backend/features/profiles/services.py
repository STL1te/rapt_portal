"""Profile (recipe) library synced from the RAPT portal API.

Uses a portal (`rapt-web`) bearer token like sync_yeasts: the public rapt-user
token returns profiles with *empty* alerts, so the portal token is required to
get profile- and step-level alerts. Read-only for now; recipe editing and
upload (portal AddOrUpdateProfile) come later.
"""

import json
import os
from pathlib import Path

import httpx
from sqlalchemy import select

from core import sync
from core.config import API_BASE
from core.db import Profile, SessionLocal
from core.serializers import row

# recipe-relevant step fields; drop deleted/createdOn/modifiedBy noise
_STEP_FIELDS = (
    "id",
    "name",
    "order",
    "controlType",
    "endType",
    "durationType",
    "operator",
    "length",
    "temperature",
    "minTemperature",
    "maxTemperature",
    "gravity",
    "pumpEnabled",
    "pumpUtilisation",
    "heatingUtilisation",
    "pidEnabled",
    "sensorDifferential",
)
_ALERT_FIELDS = ("id", "alertText", "trigger", "operator", "temperature", "gravity")
_STEP_ALERT_FIELDS = (*_ALERT_FIELDS, "length")


def _load_token() -> str:
    tok = os.environ.get("PORTAL_TOKEN", "")
    if not tok and Path(".portal_token").exists():
        tok = Path(".portal_token").read_text(encoding="utf-8")
    return tok.removeprefix("Bearer ").strip()


def _pick(src: dict, fields: tuple[str, ...]) -> dict:
    return {k: src.get(k) for k in fields}


def _step(src: dict) -> dict:
    d = _pick(src, _STEP_FIELDS)
    d["alerts"] = [_pick(a, _STEP_ALERT_FIELDS) for a in (src.get("alerts") or [])]
    return d


def sync_profiles(portal_token: str | None = None) -> int:
    """Pull the full profile library (with alerts) and upsert it; archive vanished ones."""
    token = (portal_token or _load_token()).removeprefix("Bearer ").strip()
    if not token:
        raise SystemExit("Set PORTAL_TOKEN to a portal bearer token")

    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=60) as client:
        profiles = client.get(f"{API_BASE}/api/Profiles/GetProfiles", headers=headers)
        profiles.raise_for_status()
        types = client.get(f"{API_BASE}/api/ProfileTypes/GetAll", headers=headers)
        types.raise_for_status()

    type_names = {t.get("id"): t.get("name") for t in types.json()}

    seen: set[str] = set()
    with SessionLocal() as db:
        for p in profiles.json():
            pid = p.get("id")
            if not pid:
                continue
            seen.add(pid)
            steps = sorted((p.get("steps") or []), key=lambda s: s.get("order") or 0)
            sync._upsert(
                db,
                Profile,
                {
                    "id": pid,
                    "name": p.get("name"),
                    "description": p.get("description"),
                    "public": bool(p.get("public")),
                    "rating": p.get("rating"),
                    "profile_type_id": p.get("profileTypeId"),
                    "profile_type_name": type_names.get(p.get("profileTypeId")),
                    "steps_json": json.dumps([_step(s) for s in steps], ensure_ascii=False),
                    "alerts_json": json.dumps(
                        [_pick(a, _ALERT_FIELDS) for a in (p.get("alerts") or [])],
                        ensure_ascii=False,
                    ),
                    "archived": False,
                    "updated_at": sync._now(),
                },
            )
        for existing in db.scalars(select(Profile)):
            if existing.id not in seen:
                existing.archived = True
        db.commit()

    return len(seen)


def profile_dict(p: Profile, *, include_steps: bool = True) -> dict:
    d = row(p)
    d.pop("steps_json", None)
    d.pop("alerts_json", None)
    steps = json.loads(p.steps_json) if p.steps_json else []
    d["step_count"] = len(steps)
    if include_steps:
        d["steps"] = steps
        d["alerts"] = json.loads(p.alerts_json) if p.alerts_json else []
    return d
