"""Scoring schemes: which datasets count towards a composite score and how much each one weighs."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..errors import ApiError
from ..models import Dataset, ScoreScheme
from ..schemas import SchemeIn
from ..services.composite import normalised

router = APIRouter(prefix="/schemes", tags=["schemes"])


def _out(s: ScoreScheme) -> dict[str, Any]:
    return {"id": s.id, "name": s.name, "items": normalised(s.items), "created_at": s.created_at}


def get_or_404(db: Session, scheme_id: int) -> ScoreScheme:
    s = db.get(ScoreScheme, scheme_id)
    if not s:
        raise ApiError("scheme_not_found", "评分方案不存在", 404)
    return s


def _validated(db: Session, body: SchemeIn) -> list[dict[str, Any]]:
    known = set(db.scalars(select(Dataset.name)))
    names = [i.dataset_name for i in body.items]
    if len(set(names)) != len(names):
        raise ApiError("duplicate_dataset", "同一个评测集在方案里只能出现一次")
    unknown = [n for n in names if n not in known]
    if unknown:
        raise ApiError("dataset_not_found", f"评测集不存在：{unknown[0]}", 404)
    return [{"dataset_name": i.dataset_name, "weight": i.weight} for i in body.items]


@router.get("")
def list_schemes(db: Session = Depends(get_db)):
    return [_out(s) for s in db.scalars(select(ScoreScheme).order_by(ScoreScheme.id))]


@router.post("", status_code=201)
def create_scheme(body: SchemeIn, db: Session = Depends(get_db)):
    if db.scalar(select(ScoreScheme.id).where(ScoreScheme.name == body.name)):
        raise ApiError("name_taken", f"已经有名为 {body.name} 的评分方案", 409)
    s = ScoreScheme(name=body.name, items=_validated(db, body))
    db.add(s)
    db.commit()
    return _out(s)


@router.put("/{scheme_id}")
def update_scheme(scheme_id: int, body: SchemeIn, db: Session = Depends(get_db)):
    s = get_or_404(db, scheme_id)
    if body.name != s.name and db.scalar(select(ScoreScheme.id).where(ScoreScheme.name == body.name)):
        raise ApiError("name_taken", f"已经有名为 {body.name} 的评分方案", 409)
    s.name, s.items = body.name, _validated(db, body)
    db.commit()
    return _out(s)


@router.delete("/{scheme_id}", status_code=204)
def delete_scheme(scheme_id: int, db: Session = Depends(get_db)):
    db.delete(get_or_404(db, scheme_id))
    db.commit()
