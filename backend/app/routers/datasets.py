from __future__ import annotations

import shutil

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..errors import ApiError
from ..models import Dataset, Run
from ..schemas import DatasetOut
from ..services.catalog import CAPABILITIES
from ..services.dataset_validation import KINDS, DatasetError, ingest_upload, preview

router = APIRouter(prefix="/datasets", tags=["datasets"])


def get_or_404(db: Session, dataset_id: int) -> Dataset:
    d = db.get(Dataset, dataset_id)
    if not d:
        raise ApiError("dataset_not_found", "评测集不存在", 404)
    return d


@router.get("/capabilities")
def capabilities():
    return CAPABILITIES


@router.get("", response_model=list[DatasetOut])
def list_datasets(source: str | None = None, capability: str | None = None, db: Session = Depends(get_db)):
    q = select(Dataset).order_by(Dataset.source, Dataset.capability, Dataset.name, Dataset.version.desc())
    if source:
        q = q.where(Dataset.source == source)
    if capability:
        q = q.where(Dataset.capability == capability)
    return db.scalars(q).all()


@router.post("", response_model=DatasetOut, status_code=201)
async def upload_dataset(
    name: str = Form(min_length=1, max_length=100),
    kind: str = Form(),
    description: str = Form(""),
    capability: str | None = Form(None),
    file: UploadFile = File(),
    db: Session = Depends(get_db),
):
    """Upload a custom dataset (.jsonl, or .zip with media). Re-uploading a name creates the next version."""
    if kind not in KINDS:
        raise ApiError("bad_kind", f"kind 必须是 {', '.join(KINDS)} 之一")
    if capability and capability not in CAPABILITIES:
        raise ApiError("bad_capability", f"capability 必须是 {', '.join(CAPABILITIES)} 之一")
    settings = get_settings()
    raw = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)

    latest = db.scalar(select(func.max(Dataset.version)).where(Dataset.name == name, Dataset.source == "custom"))
    ds = Dataset(name=name, version=(latest or 0) + 1, source="custom", kind=kind, capability=capability,
                 description=description, verified=False)
    db.add(ds)
    db.flush()  # get the id for the storage path
    dest = settings.datasets_dir / str(ds.id)
    try:
        ds.num_samples = ingest_upload(kind, file.filename or "", raw, dest, settings.max_upload_mb)
    except DatasetError as e:
        db.rollback()
        raise ApiError("invalid_dataset", "数据集校验未通过：" + (e.errors[0] if e.errors else ""), 422, e.errors) from e
    ds.path = str(dest)
    db.commit()
    return ds


@router.get("/{dataset_id}", response_model=DatasetOut)
def get_dataset(dataset_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, dataset_id)


@router.get("/{dataset_id}/preview")
def preview_dataset(dataset_id: int, db: Session = Depends(get_db)):
    d = get_or_404(db, dataset_id)
    if d.source != "custom" or not d.path:
        raise ApiError("no_preview", "内置基准的数据在首次评测时才会下载，暂时没有预览", 404)
    return preview(d.path)


@router.delete("/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: int, db: Session = Depends(get_db)):
    d = get_or_404(db, dataset_id)
    if d.source != "custom":
        raise ApiError("builtin", "内置基准不能删除", 409)
    if db.scalar(select(func.count()).select_from(Run).where(Run.dataset_id == d.id)):
        raise ApiError("dataset_in_use", "已有评测任务用到了这个评测集版本，不能删除（历史结果需要它）", 409)
    if d.path:
        shutil.rmtree(d.path, ignore_errors=True)
    db.delete(d)
    db.commit()
