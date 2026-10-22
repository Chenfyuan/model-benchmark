from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from ..crypto import decrypt, redact
from ..db import get_db
from ..errors import ApiError
from ..models import Dataset, ModelEndpoint, Run, RunMetric, SampleResult, utcnow
from ..schemas import EstimateIn, MetricOut, Page, ReviewIn, RunCreate, RunOut, SampleOut
from ..services.rescoring import adjusted_scores, final_verdict, rescore_run, reviewed_counts
from ..services.budget import get_budget, month_usage
from ..worker import run_dir

router = APIRouter(prefix="/runs", tags=["runs"])

DEFAULT_INPUT_TOKENS = 5000  # measured on the test gateway: 4.2k-5.6k per request, mostly gateway overhead
DEFAULT_OUTPUT_TOKENS = 150


def _fmt(m: RunMetric) -> str:
    v = None if m.value is None else m.value * (m.display_multiplier or 1.0)
    return "-" if v is None else f"{v:.{m.precision}f}{m.display_unit}"


def run_out(run: Run, headline: RunMetric | None, adjusted: dict | None = None) -> RunOut:
    return RunOut(
        id=run.id, model_id=run.model_id, model_name=run.model.name, dataset_id=run.dataset_id,
        dataset_name=run.dataset.name, dataset_version=run.dataset.version, judge_model_id=run.judge_model_id,
        judge_model_name=run.judge_model.name if run.judge_model else None, parent_run_id=run.parent_run_id,
        status=run.status, stage=run.stage, progress=run.progress, error=run.error, limit=run.limit, config=run.config,
        engine=run.engine, engine_version=run.engine_version, created_at=run.created_at, started_at=run.started_at,
        finished_at=run.finished_at, attempts=run.attempts or 1, reused_samples=run.reused_samples,
        input_tokens=run.input_tokens, output_tokens=run.output_tokens, cost=run.cost, stop_reason=run.stop_reason,
        retry_after=run.retry_after, auto_retries=run.auto_retries,
        headline=None if headline is None else {"label": headline.label, "value": headline.value, "display": _fmt(headline)},
        adjusted=None if adjusted is None else {k: adjusted[k] for k in ("adjusted", "display", "n_lenient", "n_manual")},
    )


def _headlines(db: Session, run_ids: list[int]) -> dict[int, RunMetric]:
    if not run_ids:
        return {}
    rows = db.scalars(select(RunMetric).where(RunMetric.run_id.in_(run_ids), RunMetric.primary.is_(True), RunMetric.subset == "OVERALL"))
    return {m.run_id: m for m in rows}


def _adjusted(db: Session, run_ids: list[int]) -> dict[int, dict]:
    out = {}
    for rid in (i for i, (a, m) in reviewed_counts(db, run_ids).items() if a or m):
        adj = adjusted_scores(db, rid)
        if adj:
            out[rid] = adj
    return out


def get_or_404(db: Session, run_id: int) -> Run:
    r = db.get(Run, run_id)
    if not r:
        raise ApiError("run_not_found", "评测任务不存在", 404)
    return r


# ------------------------------------------------------------------ create / estimate

def estimate_for(db: Session, model: ModelEndpoint, ds: Dataset, limit: int | None) -> dict:
    notes: list[str] = []
    n: int | None = None
    if ds.source == "custom" and ds.num_samples:
        n = min(ds.num_samples, limit) if limit else ds.num_samples
    elif limit:
        notes.append(f"内置基准按“每个子集 {limit} 题”运行，子集数在首次下载数据后才知道，所以暂时无法给出总题数。")
    else:
        notes.append("内置基准的总题数要在首次下载数据后才知道；建议先用“只跑前 20 题”试跑。")

    hist = db.execute(
        select(RunMetric.key, func.avg(RunMetric.value)).join(Run, Run.id == RunMetric.run_id).where(
            Run.model_id == model.id, Run.status == "completed", RunMetric.subset == "OVERALL",
            RunMetric.key.in_(["input_tokens_mean", "output_tokens_mean"]),
        ).group_by(RunMetric.key)
    ).all()
    hist_d = dict(hist)
    avg_in = hist_d.get("input_tokens_mean") or DEFAULT_INPUT_TOKENS
    avg_out = hist_d.get("output_tokens_mean") or DEFAULT_OUTPUT_TOKENS
    source = "history" if hist_d else "default"
    if source == "default":
        notes.append(f"这个模型还没有评测历史，token 数用默认值（输入 {DEFAULT_INPUT_TOKENS}、输出 {DEFAULT_OUTPUT_TOKENS}）估算。")

    cost = None
    if n is not None and model.price_input_per_mtok is not None and model.price_output_per_mtok is not None:
        cost = n * (avg_in * model.price_input_per_mtok + avg_out * model.price_output_per_mtok) / 1e6
    elif n is not None:
        notes.append("模型没有填写单价，只能估算 token 数，不能换算成费用。")
    return {
        "num_samples": n, "avg_input_tokens": round(avg_in), "avg_output_tokens": round(avg_out), "token_source": source,
        "total_tokens": None if n is None else round(n * (avg_in + avg_out)), "cost": cost, "notes": notes,
    }


@router.post("/estimate")
def estimate(body: EstimateIn, db: Session = Depends(get_db)):
    model, ds = db.get(ModelEndpoint, body.model_id), db.get(Dataset, body.dataset_id)
    if not model or not ds:
        raise ApiError("not_found", "模型或评测集不存在", 404)
    return estimate_for(db, model, ds, body.limit)


def _budget_problems(db: Session, models: dict[int, ModelEndpoint], datasets: dict[int, Dataset], body: RunCreate) -> list[str]:
    """Estimated overruns of the optional limits for the runs about to be created (only where the size is known)."""
    budget = get_budget(db)
    if not budget.any:
        return []
    problems: list[str] = []
    month = month_usage(db)
    total_tokens, total_cost = 0, 0.0
    for mid in body.model_ids:
        for did in body.dataset_ids:
            e = estimate_for(db, models[mid], datasets[did], body.limit)
            if e["total_tokens"] is None:
                continue
            total_tokens += e["total_tokens"]
            total_cost += e["cost"] or 0.0
            label = f"{models[mid].name} × {datasets[did].name}"
            if budget.per_run_max_tokens is not None and e["total_tokens"] > budget.per_run_max_tokens:
                problems.append(f"{label}：预计 {e['total_tokens']:,} token，超过单次上限 {int(budget.per_run_max_tokens):,}")
            if budget.per_run_max_cost is not None and e["cost"] is not None and e["cost"] > budget.per_run_max_cost:
                problems.append(f"{label}：预计约 {e['cost']:.4f}，超过单次上限 {budget.per_run_max_cost:g}")
    if budget.monthly_max_tokens is not None and month["tokens"] + total_tokens > budget.monthly_max_tokens:
        problems.append(f"本月已用 {month['tokens']:,} token，加上这次预计 {total_tokens:,}，会超过月度上限 {int(budget.monthly_max_tokens):,}")
    if budget.monthly_max_cost is not None and month["cost"] + total_cost > budget.monthly_max_cost:
        problems.append(f"本月已花约 {month['cost']:.4f}，加上这次预计约 {total_cost:.4f}，会超过月度上限 {budget.monthly_max_cost:g}")
    return problems


@router.post("", response_model=list[RunOut], status_code=201)
def create_runs(body: RunCreate, db: Session = Depends(get_db), idempotency_key: str | None = Header(default=None)):
    """Create one run per (model, dataset) pair. A repeated Idempotency-Key returns the runs already created."""
    if idempotency_key:
        prior = db.scalars(select(Run).where(Run.idempotency_key == idempotency_key).order_by(Run.id)).all()
        if prior:
            hl = _headlines(db, [r.id for r in prior])
            return [run_out(r, hl.get(r.id)) for r in prior]

    models = {m.id: m for m in db.scalars(select(ModelEndpoint).where(ModelEndpoint.id.in_(body.model_ids)))}
    datasets = {d.id: d for d in db.scalars(select(Dataset).where(Dataset.id.in_(body.dataset_ids)))}
    for mid in body.model_ids:
        if mid not in models:
            raise ApiError("model_not_found", f"模型 {mid} 不存在", 404)
    for did in body.dataset_ids:
        if did not in datasets:
            raise ApiError("dataset_not_found", f"评测集 {did} 不存在", 404)
    judge = None
    if body.judge_model_id is not None:
        judge = db.get(ModelEndpoint, body.judge_model_id)
        if not judge:
            raise ApiError("model_not_found", "裁判模型不存在", 404)
        if judge.protocol != "openai":
            raise ApiError("judge_protocol", "裁判模型目前只支持 OpenAI 格式的接口（引擎的裁判调用只走 OpenAI 格式）")

    no_judge = sorted(d.name for d in datasets.values() if d.needs_judge)
    if no_judge and body.judge_model_id is None:
        raise ApiError("judge_required", f"评测集 {'、'.join(no_judge)} 的得分完全由裁判模型给出，必须选一个裁判模型", 422)

    if not body.confirm_over_budget:
        problems = _budget_problems(db, models, datasets, body)
        if problems:
            raise ApiError("budget_exceeded", "预计会超出费用上限；确认后可以继续提交", 409, problems)

    config = {"batch_size": body.batch_size, "max_tokens": body.max_tokens, "temperature": body.temperature}
    created: list[Run] = []
    for mid in body.model_ids:
        for did in body.dataset_ids:
            r = Run(model_id=mid, dataset_id=did, judge_model_id=body.judge_model_id, limit=body.limit, config=dict(config),
                    idempotency_key=idempotency_key)
            db.add(r)
            created.append(r)
    db.commit()
    for r in created:
        db.refresh(r)
    return [run_out(r, None) for r in created]


# ------------------------------------------------------------------ list / get

@router.get("", response_model=Page)
def list_runs(
    status: str | None = None, model_id: int | None = None, dataset_id: int | None = None,
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200), db: Session = Depends(get_db),
):
    q = select(Run)
    if status:
        q = q.where(Run.status == status)
    if model_id:
        q = q.where(Run.model_id == model_id)
    if dataset_id:
        q = q.where(Run.dataset_id == dataset_id)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    runs = db.scalars(q.order_by(Run.id.desc()).limit(page_size).offset((page - 1) * page_size)).all()
    hl = _headlines(db, [r.id for r in runs])
    adj = _adjusted(db, [r.id for r in runs])
    return Page(items=[run_out(r, hl.get(r.id), adj.get(r.id)) for r in runs], total=total, page=page, page_size=page_size)


@router.get("/{run_id}", response_model=RunOut)
def get_run(run_id: int, db: Session = Depends(get_db)):
    r = get_or_404(db, run_id)
    return run_out(r, _headlines(db, [r.id]).get(r.id), _adjusted(db, [r.id]).get(r.id))


# ------------------------------------------------------------------ control

@router.post("/{run_id}/cancel", response_model=RunOut)
def cancel(run_id: int, db: Session = Depends(get_db)):
    r = get_or_404(db, run_id)
    if r.status == "queued":
        r.status, r.stage, r.finished_at = "cancelled", "done", utcnow()
    elif r.status == "running":
        r.cancel_requested = True  # the worker notices within about a second and kills the engine
    else:
        raise ApiError("not_cancellable", f"状态为 {r.status} 的任务不能取消", 409)
    db.commit()
    return run_out(r, None)


@router.post("/{run_id}/retry", response_model=RunOut)
def retry(run_id: int, db: Session = Depends(get_db)):
    """Re-queue a failed or cancelled run. Samples the previous attempt already finished are reused, not billed again."""
    r = get_or_404(db, run_id)
    if r.status not in ("failed", "cancelled"):
        raise ApiError("not_retryable", f"状态为 {r.status} 的任务不能重试", 409)
    db.execute(delete(RunMetric).where(RunMetric.run_id == r.id))
    db.execute(delete(SampleResult).where(SampleResult.run_id == r.id))
    r.status, r.stage, r.progress, r.error, r.cancel_requested = "queued", "queued", 0.0, None, False
    r.started_at = r.finished_at = None
    r.stop_reason = None
    r.attempts = (r.attempts or 1) + 1
    r.auto_retries, r.retry_after = 0, None
    r.resume = True  # the worker reuses samples the previous attempt already finished (billed once)
    db.commit()
    return run_out(r, None)


@router.post("/{run_id}/rerun", response_model=RunOut, status_code=201)
def rerun(run_id: int, db: Session = Depends(get_db)):
    """New run with the same model, dataset version, judge and configuration."""
    old = get_or_404(db, run_id)
    r = Run(model_id=old.model_id, dataset_id=old.dataset_id, judge_model_id=old.judge_model_id, limit=old.limit,
            config=dict(old.config or {}), parent_run_id=old.id)
    db.add(r)
    db.commit()
    db.refresh(r)
    return run_out(r, None)


# ------------------------------------------------------------------ results

@router.get("/{run_id}/metrics", response_model=list[MetricOut])
def metrics(run_id: int, db: Session = Depends(get_db)):
    get_or_404(db, run_id)
    return db.scalars(select(RunMetric).where(RunMetric.run_id == run_id).order_by(RunMetric.id)).all()


def _sample_filters(run_id: int, subset: str | None, correct: str | None, q: str | None):
    conds: list[Any] = [SampleResult.run_id == run_id]
    if subset:
        conds.append(SampleResult.subset == subset)
    if correct == "true":
        conds.append(func.coalesce(SampleResult.final_correct, SampleResult.is_correct).is_(True))
    elif correct == "false":
        conds.append(func.coalesce(SampleResult.final_correct, SampleResult.is_correct).is_(False))
    elif correct == "changed":  # lenient upgrades and manual decisions that differ from the engine
        conds.append(or_(SampleResult.auto_correct.is_(True), SampleResult.review_correct.is_not(None)))
    elif correct == "error":
        conds.append(SampleResult.error.is_not(None))
    if q:
        like = f"%{q}%"
        conds.append(or_(SampleResult.question.ilike(like), SampleResult.target.ilike(like), SampleResult.prediction.ilike(like)))
    return conds


@router.get("/{run_id}/samples", response_model=Page)
def samples(
    run_id: int, subset: str | None = None, correct: str | None = Query(None, pattern="^(true|false|error|changed)$"), q: str | None = None,
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db),
):
    get_or_404(db, run_id)
    conds = _sample_filters(run_id, subset, correct, q)
    total = db.scalar(select(func.count()).select_from(SampleResult).where(*conds)) or 0
    rows = db.scalars(select(SampleResult).where(*conds).order_by(SampleResult.subset, SampleResult.idx, SampleResult.id)
                      .limit(page_size).offset((page - 1) * page_size)).all()
    return Page(items=[SampleOut.model_validate(s) for s in rows], total=total, page=page, page_size=page_size)


@router.put("/{run_id}/samples/{sample_id}/review", response_model=SampleOut)
def review_sample(run_id: int, sample_id: int, body: ReviewIn, db: Session = Depends(get_db)):
    """Record a person's verdict for one answer (correct=null clears it). The engine's own verdict is kept."""
    s = db.get(SampleResult, sample_id)
    if not s or s.run_id != run_id:
        raise ApiError("sample_not_found", "没有这个样本", 404)
    s.review_correct = body.correct
    s.review_note = (body.note or None) if body.correct is not None else None
    s.reviewed_at = utcnow() if body.correct is not None else None
    s.final_correct = final_verdict(s)
    db.commit()
    return SampleOut.model_validate(s)


@router.post("/{run_id}/rescore")
def rescore(run_id: int, db: Session = Depends(get_db)):
    """Re-apply lenient matching to a finished run's stored answers (no model calls; manual reviews are kept)."""
    r = get_or_404(db, run_id)
    if r.status != "completed":
        raise ApiError("not_completed", "任务完成后才能重新评分", 409)
    return rescore_run(db, r)


@router.get("/{run_id}/adjusted")
def adjusted(run_id: int, db: Session = Depends(get_db)):
    get_or_404(db, run_id)
    return adjusted_scores(db, run_id)


@router.get("/{run_id}/samples/{sample_id}/media/{k}")
def sample_media(run_id: int, sample_id: int, k: int, db: Session = Depends(get_db)):
    s = db.get(SampleResult, sample_id)
    if not s or s.run_id != run_id or k < 0 or k >= len(s.media or []) or s.media[k].get("kind") != "file":
        raise ApiError("media_not_found", "没有这个媒体文件", 404)
    base = run_dir(run_id).resolve()
    path = (base / s.media[k]["ref"]).resolve()
    if base not in path.parents or not path.is_file():  # never serve anything outside this run's directory
        raise ApiError("media_not_found", "没有这个媒体文件", 404)
    return FileResponse(path)


@router.get("/{run_id}/log", response_class=PlainTextResponse)
def log(run_id: int, lines: int = Query(200, ge=1, le=2000), db: Session = Depends(get_db)):
    r = get_or_404(db, run_id)
    path = run_dir(run_id) / "engine.log"
    if not path.exists():
        return ""
    text = path.read_bytes()[-200_000:].decode("utf-8", errors="replace").replace("\r", "\n")
    tail = [ln for ln in text.splitlines() if ln.strip()][-lines:]
    secrets = [decrypt(r.model.api_key_enc)] + ([decrypt(r.judge_model.api_key_enc)] if r.judge_model else [])
    return redact("\n".join(tail), secrets)


def _csv_safe(v: Any) -> Any:
    return "'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v


@router.get("/{run_id}/export")
def export(run_id: int, db: Session = Depends(get_db)):
    get_or_404(db, run_id)
    cols = ["idx", "subset", "question", "target", "prediction", "extracted", "score", "is_correct", "final_correct", "auto_reason", "review_note", "latency", "input_tokens",
            "output_tokens", "error"]

    def rows():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(cols)
        yield "﻿" + buf.getvalue()  # BOM so Excel opens UTF-8 correctly
        for s in db.scalars(select(SampleResult).where(SampleResult.run_id == run_id).order_by(SampleResult.subset, SampleResult.idx)):
            buf.seek(0), buf.truncate()
            w.writerow([_csv_safe(getattr(s, c)) for c in cols])
            yield buf.getvalue()

    return StreamingResponse(rows(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="run_{run_id}_samples.csv"'})


@router.delete("/{run_id}", status_code=204)
def delete_run(run_id: int, db: Session = Depends(get_db)):
    r = get_or_404(db, run_id)
    if r.status == "running":
        raise ApiError("running", "运行中的任务不能删除，请先取消", 409)
    db.execute(delete(RunMetric).where(RunMetric.run_id == r.id))
    db.execute(delete(SampleResult).where(SampleResult.run_id == r.id))
    db.delete(r)
    db.commit()
    import shutil

    shutil.rmtree(run_dir(run_id), ignore_errors=True)
