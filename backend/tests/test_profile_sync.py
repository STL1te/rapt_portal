"""Uploading one profile must not discard other profiles' unsaved edits.

upload_profile resyncs the whole library afterwards (RAPT assigns the GUIDs), and that
resync used to overwrite every local row with the server copy — including drafts whose
edits had never been uploaded.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.db import Base, Profile
from features.profiles import services


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.is_error = False
        self.content = b"{}"

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class _FakeClient:
    """Stands in for httpx.Client: serves the library and echoes uploads."""

    def __init__(self, server_profiles, uploads):
        self._server = server_profiles
        self._uploads = uploads

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get(self, url, **_):
        if "ProfileTypes" in url:
            return _FakeResponse([{"id": "type-1", "name": "BrewZilla"}])
        return _FakeResponse(self._server)

    def post(self, url, **kwargs):
        body = kwargs.get("json")
        self._uploads.append(body)
        return _FakeResponse({**body, "id": body.get("id") or "server-new"})


def _server_profile(pid, name):
    return {
        "id": pid,
        "name": name,
        "description": "from server",
        "public": False,
        "profileTypeId": "type-1",
        "steps": [{"id": "s1", "name": "Mash", "order": 0, "temperature": 65, "alerts": []}],
        "alerts": [],
    }


@pytest.fixture
def db(monkeypatch):
    handle, path = tempfile.mkstemp(suffix=".db")
    engine = sa.create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(services, "SessionLocal", factory)
    monkeypatch.setattr(services.sync, "SessionLocal", factory, raising=False)
    yield factory
    engine.dispose()
    os.close(handle)
    Path(path).unlink(missing_ok=True)


def _local_draft(pid, name, *, draft=True):
    return Profile(
        id=pid,
        name=name,
        description="edited locally",
        public=False,
        profile_type_id="type-1",
        profile_type_name="BrewZilla",
        steps_json=json.dumps([{"id": "s1", "name": "Mash", "order": 0, "temperature": 67}]),
        alerts_json="[]",
        archived=False,
        draft=draft,
        updated_at=None,
    )


def test_sync_keeps_edits_of_profiles_not_being_uploaded(db, monkeypatch):
    """The reported bug: edit two profiles, upload one — the other lost its edits and
    stopped being a draft."""
    with db() as session:
        session.add(_local_draft("p-1", "Профиль A"))
        session.add(_local_draft("p-2", "Профиль B"))
        session.commit()

    server = [_server_profile("p-1", "Профиль A"), _server_profile("p-2", "Профиль B")]
    uploads = []
    monkeypatch.setattr(services.httpx, "Client", lambda **_: _FakeClient(server, uploads))

    services.upload_profile("p-1", "token")

    with db() as session:
        uploaded = session.get(Profile, "p-1")
        untouched = session.get(Profile, "p-2")
        # the uploaded one is now the server's copy and no longer a draft
        assert uploaded.draft is False
        assert uploaded.description == "from server"
        # the other one keeps its unsaved edits and stays a draft
        assert untouched.draft is True, "a sibling draft was overwritten by the resync"
        assert untouched.description == "edited locally"
        assert json.loads(untouched.steps_json)[0]["temperature"] == 67

    assert len(uploads) == 1, "only the requested profile is pushed to RAPT"


def test_sync_still_refreshes_profiles_without_local_edits(db, monkeypatch):
    with db() as session:
        session.add(_local_draft("p-1", "Старое имя", draft=False))
        session.commit()

    server = [_server_profile("p-1", "Новое имя")]
    monkeypatch.setattr(services.httpx, "Client", lambda **_: _FakeClient(server, []))

    services.sync_profiles("token")

    with db() as session:
        refreshed = session.get(Profile, "p-1")
        assert refreshed.name == "Новое имя"
        assert refreshed.description == "from server"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
