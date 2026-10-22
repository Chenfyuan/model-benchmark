from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ModelEndpoint
from ..services.budget import Budget, get_budget, month_usage, set_budget

router = APIRouter(prefix="/settings", tags=["settings"])


class BudgetIn(BaseModel):
    """null (or 0) means "no limit"."""

    per_run_max_tokens: float | None = Field(default=None, ge=0)
    per_run_max_cost: float | None = Field(default=None, ge=0)
    monthly_max_tokens: float | None = Field(default=None, ge=0)
    monthly_max_cost: float | None = Field(default=None, ge=0)


def _view(db: Session, budget: Budget) -> dict:
    unpriced = db.scalars(
        select(ModelEndpoint.name).where((ModelEndpoint.price_input_per_mtok.is_(None)) | (ModelEndpoint.price_output_per_mtok.is_(None)))
    ).all()
    total_models = db.scalar(select(func.count()).select_from(ModelEndpoint)) or 0
    return {
        "limits": budget.__dict__ | {},
        "usage": month_usage(db),
        # money limits cannot apply to models without a price; tell the admin which ones
        "unpriced_models": list(unpriced) if total_models else [],
    }


@router.get("/budget")
def read_budget(db: Session = Depends(get_db)):
    return _view(db, get_budget(db))


@router.put("/budget")
def write_budget(body: BudgetIn, db: Session = Depends(get_db)):
    return _view(db, set_budget(db, body.model_dump()))
