"""Side-by-side comparison of runs (the "model selection" use case)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..errors import ApiError
from ..models import Run, RunMetric, SampleResult
from ..schemas import MetricOut, Page, RunOut
from ..services.composite import compute as compute_composite
from ..services.report import compare_report
from sqlalchemy import func

from .runs import _adjusted, _headlines, run_out

router = APIRouter(prefix="/compare", tags=["compare"])
MAX_RUNS = 8


def _ids(run_ids: str) -> list[int]:
    try:
        ids = list(dict.fromkeys(int(x) for x in run_ids.split(",") if x.strip()))
    except ValueError:
        raise ApiError("bad_run_ids", "run_ids 必须是逗号分隔的任务编号") from None
    if len(ids) < 2:
        raise ApiError("too_few_runs", "至少选两个任务才能对比")
    if len(ids) > MAX_RUNS:
        raise ApiError("too_many_runs", f"一次最多对比 {MAX_RUNS} 个任务")
    return ids


def _load(db: Session, ids: list[int]) -> list[Run]:
    runs = {r.id: r for r in db.scalars(select(Run).where(Run.id.in_(ids)))}
    missing = [i for i in ids if i not in runs]
    if missing:
        raise ApiError("run_not_found", f"任务 {missing[0]} 不存在", 404)
    return [runs[i] for i in ids]


def comparability_warnings(runs: list[Run]) -> list[str]:
    """Things that make a score difference between these runs less meaningful. Compared per dataset."""
    out: list[str] = []
    by_ds: dict[str, list[Run]] = {}
    for r in runs:
        by_ds.setdefault(r.dataset.name, []).append(r)
    for name, group in by_ds.items():
        if len(group) < 2:
            continue
        label = f"评测集“{name}”："
        if len({r.dataset_id for r in group}) > 1:
            out.append(label + "对比的是不同版本的数据，题目可能不一样")
        if len({r.limit for r in group}) > 1:
            out.append(label + "题数限制不同（" + "、".join(sorted({'全量' if r.limit is None else f'每子集 {r.limit} 题' for r in group})) + "）")
        for key, text in (("max_tokens", "最大输出"), ("temperature", "温度")):
            if len({(r.config or {}).get(key) for r in group}) > 1:
                out.append(label + f"{text}设置不同")
        if len({r.judge_model_id for r in group}) > 1:
            out.append(label + "使用的裁判模型不同，开放问答的得分不可直接比较")
        if len({r.engine_version for r in group if r.engine_version}) > 1:
            out.append(label + "评测引擎版本不同")
        if any(r.limit for r in group):
            out.append(label + "限制了题数，样本少、分数波动大，只能做粗略参考")
    for r in runs:
        if r.status != "completed":
            out.append(f"任务 #{r.id}（{r.model.name}）还没有完成，状态是“{r.status}”")
    return list(dict.fromkeys(out))


@router.get("")
def compare(run_ids: str = Query(...), db: Session = Depends(get_db)):
    runs = _load(db, _ids(run_ids))
    hl = _headlines(db, [r.id for r in runs])
    metrics = {
        r.id: [MetricOut.model_validate(m) for m in db.scalars(select(RunMetric).where(RunMetric.run_id == r.id).order_by(RunMetric.id))]
        for r in runs
    }
    adj = _adjusted(db, [r.id for r in runs])
    return {
        "runs": [run_out(r, hl.get(r.id), adj.get(r.id)) for r in runs],
        "adjusted": {str(i): a for i, a in adj.items()},
        "metrics": metrics,
        "warnings": comparability_warnings(runs),
    }


@router.get("/composite")
def composite(run_ids: str = Query(...), scheme_id: int = Query(...), db: Session = Depends(get_db)):
    """Weighted composite score per model over the compared runs, for a saved scheme."""
    from ..models import ScoreScheme

    scheme = db.get(ScoreScheme, scheme_id)
    if not scheme:
        raise ApiError("scheme_not_found", "评分方案不存在", 404)
    return compute_composite(db, scheme, _load(db, _ids(run_ids)))


@router.get("/report", response_class=HTMLResponse)
def compare_report_html(run_ids: str = Query(...), download: bool = False, scheme_id: int | None = None, db: Session = Depends(get_db)):
    runs = _load(db, _ids(run_ids))
    unfinished = [r.id for r in runs if r.status != "completed"]
    if unfinished:
        raise ApiError("not_completed", f"任务 {unfinished[0]} 还没有完成，完成后才能导出对比报告", 409)
    headers = {"Content-Disposition": 'attachment; filename="compare_report.html"'} if download else {}
    scheme = None
    if scheme_id is not None:
        from ..models import ScoreScheme

        scheme = db.get(ScoreScheme, scheme_id)
        if not scheme:
            raise ApiError("scheme_not_found", "评分方案不存在", 404)
    return HTMLResponse(compare_report(db, runs, comparability_warnings(runs), scheme), headers=headers)


@router.get("/samples", response_model=Page)
def compare_samples(
    run_ids: str = Query(...), view: str = Query("diff", pattern="^(diff|all_wrong|all)$"), subset: str | None = None,
    page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=50), db: Session = Depends(get_db),
):
    """Samples aligned across runs of one dataset version, keyed by (subset, idx).

    view=diff: models disagree on correctness; view=all_wrong: nobody got it right; view=all.
    """
    ids = _ids(run_ids)
    runs = _load(db, ids)
    if len({r.dataset_id for r in runs}) > 1:
        raise ApiError("different_datasets", "逐题对比只能用于同一个评测集版本的任务")

    q = select(SampleResult.run_id, SampleResult.subset, SampleResult.idx, func.coalesce(SampleResult.final_correct, SampleResult.is_correct)).where(SampleResult.run_id.in_(ids))
    if subset:
        q = q.where(SampleResult.subset == subset)
    grid: dict[tuple[str, int], dict[int, bool | None]] = {}
    for run_id, sub, idx, ok in db.execute(q):
        grid.setdefault((sub, idx), {})[run_id] = ok

    def keep(cells: dict[int, bool | None]) -> bool:
        vals = [cells.get(i) for i in ids]
        if view == "all":
            return True
        if view == "all_wrong":
            return all(v is False for v in vals)
        known = [v for v in vals if v is not None]
        return len(known) >= 2 and len(set(known)) > 1  # at least two runs have a verdict and they disagree

    keys = sorted(k for k, cells in grid.items() if keep(cells))
    total = len(keys)
    page_keys = keys[(page - 1) * page_size: page * page_size]

    rows: list[dict[str, Any]] = []
    if page_keys:
        wanted = set(page_keys)
        samples = db.scalars(select(SampleResult).where(SampleResult.run_id.in_(ids), SampleResult.idx.in_({k[1] for k in page_keys}))).all()
        by_key: dict[tuple[str, int], dict[int, SampleResult]] = {}
        for s in samples:
            if (s.subset, s.idx) in wanted:
                by_key.setdefault((s.subset, s.idx), {})[s.run_id] = s
        for key in page_keys:
            cells = by_key.get(key, {})
            first = next((cells[i] for i in ids if i in cells), None)
            if first is None:
                continue
            rows.append({
                "subset": key[0], "idx": key[1], "question": first.question, "target": first.target,
                "media": first.media, "media_run_id": first.run_id, "media_sample_id": first.id,
                "results": {
                    str(i): None if i not in cells else {
                        "sample_id": cells[i].id, "is_correct": cells[i].final_correct if cells[i].final_correct is not None else cells[i].is_correct,
                        "engine_correct": cells[i].is_correct, "auto_reason": cells[i].auto_reason, "reviewed": cells[i].review_correct is not None, "score": cells[i].score,
                        "prediction": cells[i].prediction, "extracted": cells[i].extracted, "tool_calls": cells[i].tool_calls,
                        "latency": cells[i].latency, "error": cells[i].error,
                    }
                    for i in ids
                },
            })
    return Page(items=rows, total=total, page=page, page_size=page_size)
