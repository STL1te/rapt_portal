"""Profile (recipe) library synced from the RAPT portal API.

Uses a portal (`rapt-web`) bearer token like sync_yeasts: the public rapt-user
token returns profiles with *empty* alerts, so the portal token is required to
get profile- and step-level alerts. Read-only for now; recipe editing and
upload (portal AddOrUpdateProfile) come later.
"""

import json
import logging
import os
import uuid
from pathlib import Path

import httpx
from sqlalchemy import select

from core import sync
from core.config import API_BASE
from core.db import Profile, SessionLocal
from core.serializers import row

logger = logging.getLogger(__name__)

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


def _step(src: dict, order: int | None = None) -> dict:
    d = _pick(src, _STEP_FIELDS)
    if order is not None:
        d["order"] = order
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
                    "draft": False,  # server copy is authoritative, clears any local draft
                    "updated_at": sync._now(),
                },
            )
        for existing in db.scalars(select(Profile)):
            if existing.id not in seen and not existing.id.startswith("local-"):
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


# --- local editing (Phase 2) -------------------------------------------------


def _payload_row(payload: dict, *, pid: str) -> dict:
    """Map an editor payload onto Profile columns. Always a draft; rating/type_name
    are display-only and left untouched on update by the caller."""
    steps = payload.get("steps") or []
    return {
        "id": pid,
        "name": payload.get("name"),
        "description": payload.get("description"),
        "public": bool(payload.get("public")),
        "profile_type_id": payload.get("profile_type_id"),
        "profile_type_name": payload.get("profile_type_name"),
        "steps_json": json.dumps(
            [_step(s, order=i) for i, s in enumerate(steps)], ensure_ascii=False
        ),
        "alerts_json": json.dumps(
            [_pick(a, _ALERT_FIELDS) for a in (payload.get("alerts") or [])],
            ensure_ascii=False,
        ),
        "archived": False,
        "draft": True,
        "updated_at": sync._now(),
    }


def create_profile(payload: dict) -> dict:
    pid = "local-" + uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(Profile(**_payload_row(payload, pid=pid)))
        db.commit()
        return profile_dict(db.get(Profile, pid))


def update_profile(profile_id: str, payload: dict) -> dict | None:
    with SessionLocal() as db:
        p = db.get(Profile, profile_id)
        if not p:
            return None
        for k, v in _payload_row(payload, pid=profile_id).items():
            if k != "id":
                setattr(p, k, v)
        db.commit()
        return profile_dict(p)


def delete_profile(profile_id: str) -> bool:
    with SessionLocal() as db:
        p = db.get(Profile, profile_id)
        if not p:
            return False
        db.delete(p)
        db.commit()
        return True


# --- upload to RAPT (portal AddOrUpdateProfile) ------------------------------
#
# GUIDs (profile id, step id, alert id) are assigned by RAPT, not the client:
# a new recipe posts empty ids and the server fills them in. So a locally-created
# draft carries a "local-<uuid>" placeholder id that we send blank and drop after
# the post + resync brings back the server's authoritative copy.


def _strip(v):
    """Drop keys that are None or "" (empty GUIDs / unset numeric fields). RAPT
    500s on empty-string GUIDs and null numeric fields; the web app omits them."""
    if isinstance(v, dict):
        return {k: _strip(x) for k, x in v.items() if x is not None and x != ""}
    if isinstance(v, list):
        return [_strip(x) for x in v]
    # RAPT's length/order are Int32 — pydantic floats (3600.0) fail .NET's int
    # parser; emit whole floats as int (decimals like 52.5 stay float).
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def _alert_body(a: dict, *, blank_ids: bool, step: bool) -> dict:
    fields = _STEP_ALERT_FIELDS if step else _ALERT_FIELDS
    body = _pick(a, fields)
    body["id"] = "" if (blank_ids or not a.get("id")) else a["id"]
    body["deleted"] = False
    return body


def _step_body(s: dict, *, profile_id: str, blank_ids: bool) -> dict:
    body = _pick(s, _STEP_FIELDS)
    step_id = "" if (blank_ids or not s.get("id")) else s["id"]
    body["id"] = step_id
    body["profileId"] = "" if blank_ids else profile_id
    body["deleted"] = False
    body["alerts"] = [
        {**_alert_body(a, blank_ids=blank_ids, step=True), "profileStepId": step_id}
        for a in (s.get("alerts") or [])
    ]
    return body


def _upload_body(p: Profile) -> dict:
    new = p.id.startswith("local-")
    steps = json.loads(p.steps_json) if p.steps_json else []
    alerts = json.loads(p.alerts_json) if p.alerts_json else []
    return _strip(
        {
            "id": "" if new else p.id,
            "name": p.name,
            "description": p.description,
            "public": bool(p.public),
            "profileTypeId": p.profile_type_id,
            "deleted": False,
            "alerts": [_alert_body(a, blank_ids=new, step=False) for a in alerts],
            "steps": [_step_body(s, profile_id=p.id, blank_ids=new) for s in steps],
        }
    )


def upload_profile(profile_id: str, portal_token: str | None = None) -> dict:
    """POST the draft to RAPT, then resync so the server's copy (with real GUIDs)
    replaces the local draft."""
    token = (portal_token or _load_token()).removeprefix("Bearer ").strip()
    if not token:
        raise SystemExit("Set PORTAL_TOKEN to a portal bearer token")

    with SessionLocal() as db:
        p = db.get(Profile, profile_id)
        if not p:
            raise SystemExit(f"profile {profile_id} not found")
        body = _upload_body(p)
        was_local = p.id.startswith("local-")

    headers = {"Authorization": f"Bearer {token}"}
    logger.info(
        "AddOrUpdateProfile %s payload: %s",
        profile_id,
        json.dumps(body, ensure_ascii=False),
    )
    with httpx.Client(timeout=60) as client:
        resp = client.post(
            f"{API_BASE}/api/Profiles/AddOrUpdateProfile", headers=headers, json=body
        )
        if resp.is_error:
            # raise_for_status drops the body; RAPT's 500 body has the real reason
            logger.error("AddOrUpdateProfile %s -> %s: %s", profile_id, resp.status_code, resp.text)
            raise RuntimeError(f"RAPT {resp.status_code}: {resp.text or '(empty body)'}")
        saved = resp.json() if resp.content else None

    new_id = saved.get("id") if isinstance(saved, dict) else None
    synced = sync_profiles(token)

    if was_local:
        with SessionLocal() as db:
            stale = db.get(Profile, profile_id)
            if stale:
                db.delete(stale)
                db.commit()

    return {
        "status": "ok",
        "new_id": new_id or (None if was_local else profile_id),
        "synced": synced,
    }
