"""What is processing the queue right now (for the run list header and "why is nothing starting?")."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Run, Worker, utcnow

router = APIRouter(prefix="/workers", tags=["workers"])


@router.get("")
def workers(db: Session = Depends(get_db)):
    cutoff = utcnow() - timedelta(seconds=get_settings().worker_stale_sec)
    rows = db.scalars(select(Worker).where(Worker.heartbeat_at > cutoff).order_by(Worker.host, Worker.pid, Worker.id)).all()
    counts = dict(db.execute(select(Run.status, func.count()).where(Run.status.in_(("queued", "running"))).group_by(Run.status)).all())
    return {
        "slots": [{"id": w.id, "host": w.host, "run_id": w.run_id, "started_at": w.started_at} for w in rows],
        "alive": len(rows), "idle": sum(1 for w in rows if w.run_id is None),
        "queued": counts.get("queued", 0), "running": counts.get("running", 0),
    }
