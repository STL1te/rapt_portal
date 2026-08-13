"""Self-check for system job retention. Run: uv run pytest tests/"""

import sys
import uuid
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core import db as db_module
from core.db import Base, SystemJob
from features.system import services


def _job(created_at, status):
    return SystemJob(id=uuid.uuid4().hex, kind="base_sync", status=status, created_at=created_at)


def test_prune_keeps_recent_and_active(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    monkeypatch.setattr(services, "SessionLocal", session_factory)

    now = services._utcnow()
    old, recent = now - timedelta(days=4), now - timedelta(days=2)
    with session_factory() as db:
        db.add_all(
            [
                _job(old, "done"),
                _job(old, "failed"),
                _job(old, "running"),  # a 4-day hang stays visible
                _job(recent, "done"),
            ]
        )
        db.commit()

    assert services.prune_old_jobs() == 2
    with session_factory() as db:
        assert {(j.status, j.created_at) for j in db.query(SystemJob)} == {
            ("running", old.replace(tzinfo=None)),
            ("done", recent.replace(tzinfo=None)),
        }
