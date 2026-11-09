"""Self-check for the batch tracker API. Run: uv run pytest tests/"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.db import Base
from features.batches import router as batches


def test_batch_lifecycle(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr(batches, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    app = FastAPI()
    app.include_router(batches.router)
    client = TestClient(app)

    body = {
        "name": "Клон Короны Экстра",
        "bottled_on": "2026-11-01",
        "volume_l": 20,
        "carbonation_until": "2026-11-15",
        "conditioning_until": "2026-12-01",
    }
    assert (
        client.post("/api/batches", json={**body, "carbonation_until": "2026-10-01"}).status_code
        == 422
    )

    created = client.post("/api/batches", json=body).json()
    assert created["remaining_l"] == 20 and created["volumes"] == []

    url = f"/api/batches/{created['id']}"
    assert (
        client.post(f"{url}/volumes", json={"recorded_on": "2026-10-30", "volume_l": 5}).status_code
        == 422
    )
    client.post(f"{url}/volumes", json={"recorded_on": "2026-12-05", "volume_l": 12})
    after = client.post(f"{url}/volumes", json={"recorded_on": "2026-12-03", "volume_l": 15}).json()
    assert [v["volume_l"] for v in after["volumes"]] == [15, 12]  # ordered by day
    assert after["remaining_l"] == 12

    after = client.delete(f"{url}/volumes/{after['volumes'][1]['id']}").json()
    assert after["remaining_l"] == 15

    finished = client.put(url, json={**body, "finished_on": "2026-12-20"}).json()
    assert finished["finished_on"] == "2026-12-20"
    assert client.get("/api/batches").json()[0]["finished_on"] == "2026-12-20"

    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404
