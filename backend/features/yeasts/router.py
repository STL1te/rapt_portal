"""Local yeast catalog synced from the RAPT portal inventory."""

from fastapi import APIRouter
from sqlalchemy import select

from core.db import SessionLocal, Yeast
from core.serializers import row

router = APIRouter()


@router.get("/api/yeasts")
def list_yeasts(q: str | None = None, type: str | None = None) -> list[dict]:
    with SessionLocal() as db:
        stmt = select(Yeast).where(Yeast.archived.is_(False))
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(
                Yeast.name.ilike(like) | Yeast.product_id.ilike(like) | Yeast.laboratory.ilike(like)
            )
        if type:
            stmt = stmt.where(Yeast.type == type)
        stmt = stmt.order_by(Yeast.laboratory, Yeast.name)
        return [row(y) for y in db.scalars(stmt)]
