from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..crypto import decrypt, encrypt, mask
from ..db import get_db
from ..errors import ApiError
from ..models import ModelEndpoint, Run
from ..schemas import ModelCreate, ModelOut, ModelUpdate
from ..services.model_check import check_model

router = APIRouter(prefix="/models", tags=["models"])


def get_or_404(db: Session, model_id: int) -> ModelEndpoint:
    m = db.get(ModelEndpoint, model_id)
    if not m:
        raise ApiError("model_not_found", "模型不存在", 404)
    return m


@router.get("", response_model=list[ModelOut])
def list_models(db: Session = Depends(get_db)):
    return db.scalars(select(ModelEndpoint).order_by(ModelEndpoint.id)).all()


@router.post("", response_model=ModelOut, status_code=201)
def create_model(body: ModelCreate, db: Session = Depends(get_db)):
    if db.scalar(select(ModelEndpoint.id).where(ModelEndpoint.name == body.name)):
        raise ApiError("name_taken", f"已经有名为 {body.name} 的模型", 409)
    m = ModelEndpoint(
        name=body.name, protocol=body.protocol, base_url=body.base_url.rstrip("/"), model_name=body.model_name,
        api_key_enc=encrypt(body.api_key), api_key_hint=mask(body.api_key),
        price_input_per_mtok=body.price_input_per_mtok, price_output_per_mtok=body.price_output_per_mtok,
        max_parallel_runs=body.max_parallel_runs,
    )
    db.add(m)
    db.commit()
    return m


@router.get("/{model_id}", response_model=ModelOut)
def get_model(model_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, model_id)


@router.put("/{model_id}", response_model=ModelOut)
def update_model(model_id: int, body: ModelUpdate, db: Session = Depends(get_db)):
    m = get_or_404(db, model_id)
    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"] != m.name and db.scalar(select(ModelEndpoint.id).where(ModelEndpoint.name == data["name"])):
        raise ApiError("name_taken", f"已经有名为 {data['name']} 的模型", 409)
    key = data.pop("api_key", None)
    if key:
        m.api_key_enc, m.api_key_hint = encrypt(key), mask(key)
    if "base_url" in data and data["base_url"]:
        data["base_url"] = data["base_url"].rstrip("/")
    for k, v in data.items():
        setattr(m, k, v)
    m.last_check = None  # connection details changed; the old test no longer applies
    db.commit()
    return m


@router.delete("/{model_id}", status_code=204)
def delete_model(model_id: int, db: Session = Depends(get_db)):
    m = get_or_404(db, model_id)
    used = db.scalar(select(func.count()).select_from(Run).where((Run.model_id == m.id) | (Run.judge_model_id == m.id)))
    if used:
        raise ApiError("model_in_use", f"有 {used} 个评测任务用到了这个模型，不能删除", 409)
    db.delete(m)
    db.commit()


@router.post("/{model_id}/check")
def check(model_id: int, db: Session = Depends(get_db)):
    m = get_or_404(db, model_id)
    result = check_model(m.protocol, m.base_url, decrypt(m.api_key_enc), m.model_name)
    m.last_check = result
    db.commit()
    return result
