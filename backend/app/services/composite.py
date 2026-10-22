"""Composite score: a weighted average of one model's scores on several datasets, with weights from a saved scheme.

Rules (kept simple and explicit so the number can always be explained):
  * a model gets a composite only if every dataset in the scheme has a finished run of it among the compared runs;
  * the score of a run is its reviewed score when it has one, else the engine's main metric;
  * only percentage-type metrics (0..100 %) can be averaged; other kinds make the composite unavailable;
  * weights are relative: they are normalised to sum to 100 %.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Run, RunMetric, ScoreScheme
from .rescoring import adjusted_scores


def normalised(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    total = sum(float(i["weight"]) for i in items) or 1.0
    return [{**i, "weight_pct": float(i["weight"]) / total * 100} for i in items]


def compute(db: Session, scheme: ScoreScheme, runs: list[Run]) -> dict[str, Any]:
    items = normalised(scheme.items)
    models: dict[int, str] = {}
    for r in runs:
        models.setdefault(r.model_id, r.model.name)
    out = []
    for model_id, model_name in models.items():
        parts, missing, problems = [], [], []
        for it in items:
            cands = [r for r in runs if r.model_id == model_id and r.dataset.name == it["dataset_name"] and r.status == "completed"]
            if not cands:
                missing.append(it["dataset_name"])
                continue
            run = max(cands, key=lambda r: r.id)  # the newest finished run
            head = db.scalar(select(RunMetric).where(RunMetric.run_id == run.id, RunMetric.primary.is_(True), RunMetric.subset == "OVERALL"))
            if head is None or head.value is None:
                problems.append(f"{it['dataset_name']}：任务 #{run.id} 没有主指标")
                continue
            if head.display_unit != "%":
                problems.append(f"{it['dataset_name']}：主指标 {head.label} 不是百分比，不能平均")
                continue
            adj = adjusted_scores(db, run.id)
            value = (adj["adjusted"] if adj else head.value) * 100
            parts.append({"dataset_name": it["dataset_name"], "weight_pct": it["weight_pct"], "value": value, "run_id": run.id,
                          "metric": head.label, "reviewed": bool(adj), "limit": run.limit})
        complete = not missing and not problems
        out.append({
            "model_id": model_id, "model_name": model_name, "parts": parts, "missing": missing, "problems": problems,
            "score": sum(p["value"] * p["weight_pct"] / 100 for p in parts) if complete else None,
            "trial": any(p["limit"] for p in parts),
        })
    out.sort(key=lambda m: (m["score"] is None, -(m["score"] or 0)))
    return {"scheme": {"id": scheme.id, "name": scheme.name, "items": items}, "models": out}
