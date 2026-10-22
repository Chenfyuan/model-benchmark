"""Lenient answer matching and manual review, layered on top of the engine's verdicts.

The engine's own score (`SampleResult.is_correct` / `score`) is never overwritten. On top of it:
  auto_correct    - the platform's own re-check disagrees with the engine: True = right although the engine said wrong (lenient
                    matching, e.g. "6.8%" vs "6.8"), False = wrong although the engine said right (tool-call argument values)
  review_correct  - a person's decision, wins over everything
  final_correct   - review_correct, else auto_correct, else is_correct; what filters / comparisons use
The "adjusted" score recomputes the headline from the final verdicts, and is only offered when the engine's headline is a
plain mean of per-sample scores (checked, not assumed).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Run, RunMetric, SampleResult

NUMBER = re.compile(r"^[^\d\-+.]{0,3}([-+]?(?:\d[\d,]*)(?:\.\d+)?|[-+]?\.\d+)\s*(%|％)?\s*[A-Za-z$€¥£元]{0,6}\.?$")
STRIP = re.compile(r"[\s\"'“”‘’`.,;:!?，。；：！？、()（）\[\]{}]+")


def _norm(s: str) -> str:
    return STRIP.sub("", unicodedata.normalize("NFKC", s).casefold())


def _number(s: str) -> float | None:
    m = NUMBER.match(unicodedata.normalize("NFKC", s).strip())
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def lenient_match(targets: str | None, prediction: str | None, extracted: str | None) -> str | None:
    """Reason string when the answer matches a target after normalisation, else None.

    Deliberately conservative: case / spacing / punctuation / full-width differences, and numbers that are equal once
    %, thousands separators, a currency sign or a short unit are ignored. No substring matching.
    """
    if not targets:
        return None
    answers = [a.strip() for a in (extracted, prediction) if a and a.strip()]
    goals = [t.strip() for t in targets.split(", ") if t.strip()] + ([targets.strip()] if ", " in targets else [])
    for a in answers:
        if len(a) > 200:
            continue
        for t in goals:
            if _norm(a) == _norm(t) and _norm(t):
                return "忽略大小写、空格和标点后与标准答案一致"
            na, nt = _number(a), _number(t)
            if na is not None and nt is not None and abs(na - nt) <= 1e-9 * max(1.0, abs(nt)):
                return f"数值相同（“{a}” 与 “{t}”，忽略 %、千分位和单位）"
    return None


def final_verdict(s: SampleResult) -> bool | None:
    if s.review_correct is not None:
        return s.review_correct
    if s.auto_correct is not None:
        return s.auto_correct
    return s.is_correct


def apply_lenient(s: SampleResult | dict[str, Any]) -> None:
    """Fill auto_* / final_correct on a sample (ORM row or the dict the parser produced). Leaves manual reviews alone."""
    get = (lambda k: s.get(k)) if isinstance(s, dict) else (lambda k: getattr(s, k))

    def put(k: str, v: Any) -> None:
        if isinstance(s, dict):
            s[k] = v
        else:
            setattr(s, k, v)

    reason = None
    if get("is_correct") is False and not get("error") and not get("tool_calls"):
        reason = lenient_match(get("target"), get("prediction"), get("extracted"))
    put("auto_correct", True if reason else None)
    put("auto_reason", reason)
    review = get("review_correct")
    put("final_correct", review if review is not None else (True if reason else get("is_correct")))


def rescore_run(db: Session, run: Run) -> dict[str, int]:
    """Re-run the platform's own checks over a finished run's stored answers (no model calls). Judge-graded runs are skipped.

    Tool-call datasets get the argument-value check, everything else the lenient matching.
    """
    if run.judge_model_id:
        return {"checked": 0, "upgraded": 0, "downgraded": 0, "skipped_reason_judge": 1}
    rows = db.scalars(select(SampleResult).where(SampleResult.run_id == run.id)).all()
    up = down = 0
    if run.dataset.kind == "fc":
        from .tool_check import apply_tool_check

        down = apply_tool_check(rows, load_dataset_rows(run.dataset.path))
    else:
        for s in rows:
            apply_lenient(s)
            up += s.auto_correct is True
    db.commit()
    return {"checked": len(rows), "upgraded": up, "downgraded": down, "skipped_reason_judge": 0}


def load_dataset_rows(path: str | None) -> list[dict]:
    """The rows of a stored custom dataset (data.jsonl), in order; empty for built-in benchmarks."""
    import json
    from pathlib import Path

    f = Path(path) / "data.jsonl" if path else None
    if not f or not f.is_file():
        return []
    return [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------- adjusted score

def _mean(vals: list[float]) -> float | None:
    return sum(vals) / len(vals) if vals else None


def adjusted_scores(db: Session, run_id: int) -> dict[str, Any] | None:
    """Headline recomputed from final verdicts, or None if nothing was changed / it cannot be recomputed faithfully."""
    head = db.scalar(select(RunMetric).where(RunMetric.run_id == run_id, RunMetric.primary.is_(True), RunMetric.subset == "OVERALL"))
    if head is None or head.value is None:
        return None
    rows = db.scalars(select(SampleResult).where(SampleResult.run_id == run_id)).all()
    n_auto = sum(1 for s in rows if s.review_correct is None and s.auto_correct is True)
    n_args = sum(1 for s in rows if s.review_correct is None and s.auto_correct is False)
    n_manual = sum(1 for s in rows if s.review_correct is not None and s.review_correct != s.is_correct)
    if not (n_auto or n_args or n_manual):
        return None

    def adj(s: SampleResult) -> float | None:
        if s.score is None:
            return None if s.is_correct is None and final_verdict(s) is None else (1.0 if final_verdict(s) else 0.0)
        fv = final_verdict(s)
        return s.score if fv == s.is_correct or fv is None else (1.0 if fv else 0.0)

    by_sub: dict[str, list[SampleResult]] = {}
    for s in rows:
        by_sub.setdefault(s.subset, []).append(s)
    eng_sub = {s: _mean([x.score for x in xs if x.score is not None]) for s, xs in by_sub.items()}
    adj_sub = {s: _mean([a for a in (adj(x) for x in xs) if a is not None]) for s, xs in by_sub.items()}

    # Which aggregation did the engine use for OVERALL: mean over all samples, or mean of subset means?
    flat_e = _mean([x.score for x in rows if x.score is not None])
    macro_e = _mean([v for v in eng_sub.values() if v is not None])
    flat_a = _mean([a for a in (adj(x) for x in rows) if a is not None])
    macro_a = _mean([v for v in adj_sub.values() if v is not None])
    if flat_e is not None and abs(flat_e - head.value) < 1e-6:
        overall = flat_a
    elif macro_e is not None and abs(macro_e - head.value) < 1e-6:
        overall = macro_a
    else:
        return None  # the headline is not a plain mean of sample scores (F1, BLEU...): do not guess
    if overall is None:
        return None
    return {
        "label": head.label, "engine": head.value, "adjusted": overall,
        "display": f"{overall * (head.display_multiplier or 1.0):.{head.precision}f}{head.display_unit}",
        "n_lenient": n_auto, "n_args": n_args, "n_manual": n_manual,
        "subsets": {s: {"engine": eng_sub[s], "adjusted": adj_sub[s], "num": len(xs)} for s, xs in by_sub.items() if s},
    }


def reviewed_counts(db: Session, run_ids: list[int]) -> dict[int, tuple[int, int]]:
    """(lenient upgrades, manual reviews) per run, for list pages."""
    if not run_ids:
        return {}
    q = select(SampleResult.run_id, func.sum(SampleResult.auto_correct.is_not(None)), func.sum(SampleResult.review_correct.is_not(None))) \
        .where(SampleResult.run_id.in_(run_ids)).group_by(SampleResult.run_id)
    return {rid: (int(a or 0), int(m or 0)) for rid, a, m in db.execute(q)}
