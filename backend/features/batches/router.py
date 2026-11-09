"""Bottled-batch tracker: phase dates, remaining volume, stop when it runs out."""

from datetime import date

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, select

from core.db import Batch, BatchVolume, SessionLocal
from core.serializers import row

router = APIRouter()


class BatchIn(BaseModel):
    name: str = Field(min_length=1)
    bottled_on: date
    volume_l: float = Field(gt=0)
    carbonation_until: date
    conditioning_until: date
    finished_on: date | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _ordered(self):
        if not self.bottled_on <= self.carbonation_until <= self.conditioning_until:
            raise ValueError("ожидается розлив ≤ конец газации ≤ конец созревания")
        if self.finished_on and self.finished_on < self.bottled_on:
            raise ValueError("партия не может закончиться раньше розлива")
        return self


class VolumeIn(BaseModel):
    recorded_on: date
    volume_l: float = Field(ge=0)


def _serialize(db, batch: Batch) -> dict:
    volumes = db.scalars(
        select(BatchVolume)
        .where(BatchVolume.batch_id == batch.id)
        .order_by(BatchVolume.recorded_on, BatchVolume.id)
    ).all()
    return {
        **row(batch),
        "volumes": [row(v) for v in volumes],
        "remaining_l": volumes[-1].volume_l if volumes else batch.volume_l,
    }


def _get(db, batch_id: int) -> Batch:
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(404, "batch not found")
    return batch


@router.get("/api/batches")
def list_batches() -> list[dict]:
    with SessionLocal() as db:
        batches = db.scalars(select(Batch).order_by(Batch.bottled_on.desc(), Batch.id.desc()))
        return [_serialize(db, b) for b in batches]


@router.get("/api/batches/{batch_id}")
def get_batch(batch_id: int) -> dict:
    with SessionLocal() as db:
        return _serialize(db, _get(db, batch_id))


@router.post("/api/batches", status_code=status.HTTP_201_CREATED)
def create_batch(body: BatchIn) -> dict:
    with SessionLocal() as db:
        batch = Batch(**body.model_dump())
        db.add(batch)
        db.commit()
        return _serialize(db, batch)


@router.put("/api/batches/{batch_id}")
def update_batch(batch_id: int, body: BatchIn) -> dict:
    with SessionLocal() as db:
        batch = _get(db, batch_id)
        for key, value in body.model_dump().items():
            setattr(batch, key, value)
        db.commit()
        return _serialize(db, batch)


@router.delete("/api/batches/{batch_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_batch(batch_id: int) -> None:
    with SessionLocal() as db:
        db.execute(delete(BatchVolume).where(BatchVolume.batch_id == batch_id))
        db.delete(_get(db, batch_id))
        db.commit()


@router.post("/api/batches/{batch_id}/volumes", status_code=status.HTTP_201_CREATED)
def add_volume(batch_id: int, body: VolumeIn) -> dict:
    with SessionLocal() as db:
        batch = _get(db, batch_id)
        if body.recorded_on < batch.bottled_on:
            raise HTTPException(422, "остаток не может быть записан раньше розлива")
        db.add(BatchVolume(batch_id=batch_id, **body.model_dump()))
        db.commit()
        return _serialize(db, batch)


@router.delete("/api/batches/{batch_id}/volumes/{volume_id}")
def delete_volume(batch_id: int, volume_id: int) -> dict:
    with SessionLocal() as db:
        batch = _get(db, batch_id)
        db.execute(
            delete(BatchVolume).where(BatchVolume.id == volume_id, BatchVolume.batch_id == batch_id)
        )
        db.commit()
        return _serialize(db, batch)
