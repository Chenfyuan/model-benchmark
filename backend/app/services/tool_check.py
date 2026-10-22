"""Check the *values* of a model's tool-call arguments against what a custom dataset expects.

The engine only judges whether a tool should have been called and whether the call is well formed. A dataset row may add

    "expected_calls": [{"name": "get_weather", "arguments": {"city": "Paris"}}]

and the platform then compares the model's calls with it (nothing is sent to a model; it is a plain comparison):
  * every expected call must be matched by a distinct actual call with the same tool name;
  * every argument listed in `arguments` must be present with an equal value; arguments the model adds are ignored;
  * strings compare ignoring case and surrounding spaces, numbers numerically (5 == "5" == 5.0), lists and objects recursively;
  * a value can also be {"$any": true} (must be present, any value) or {"$regex": "^Par"} (the text must match);
  * calls the model made that match no expected call are an error unless the row sets "allow_extra_calls": true.
"""
from __future__ import annotations

import json
import re
from typing import Any

MISSING = object()


def validate_expected(row: dict) -> list[str]:
    """Problems with a dataset row's expectation (empty = fine or none given)."""
    if "expected_calls" not in row:
        return []
    exp, errs = row["expected_calls"], []
    names = {t["function"]["name"] for t in row.get("tools") or [] if isinstance(t, dict) and isinstance(t.get("function"), dict)}
    if not row.get("should_call_tool"):
        errs.append("expected_calls 只能用于 should_call_tool 为 true 的样本")
    if not isinstance(exp, list) or not exp:
        return errs + ["expected_calls 必须是非空列表"]
    for c in exp:
        if not isinstance(c, dict) or not isinstance(c.get("name"), str) or not isinstance(c.get("arguments", {}), dict):
            errs.append("expected_calls 的每一项需要 name（字符串）和 arguments（对象）")
        elif names and c["name"] not in names:
            errs.append(f"expected_calls 里的工具 {c['name']} 不在 tools 里")
        else:
            for v in c.get("arguments", {}).values():
                if isinstance(v, dict) and "$regex" in v:
                    try:
                        re.compile(v["$regex"])
                    except re.error:
                        errs.append(f"$regex 不是合法的正则：{v['$regex']}")
    if "allow_extra_calls" in row and not isinstance(row["allow_extra_calls"], bool):
        errs.append("allow_extra_calls 必须是 true 或 false")
    return errs


def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip().replace(",", ""))
        except ValueError:
            return None
    return None


def values_equal(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict) and ("$any" in expected or "$regex" in expected):
        if actual is MISSING:
            return False
        return True if "$any" in expected else bool(re.search(expected["$regex"], str(actual)))
    if actual is MISSING:
        return False
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(values_equal(v, actual.get(k, MISSING)) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(expected) == len(actual) and all(values_equal(e, a) for e, a in zip(expected, actual))
    if isinstance(expected, bool) or isinstance(actual, bool):
        return expected == actual or str(expected).lower() == str(actual).lower()
    en, an = _num(expected), _num(actual)
    if en is not None and an is not None:
        return abs(en - an) <= 1e-9 * max(1.0, abs(en))
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.strip().casefold() == actual.strip().casefold()
    return expected == actual


def _args(call: dict) -> dict | None:
    a = call.get("arguments")
    if isinstance(a, str):
        try:
            a = json.loads(a)
        except json.JSONDecodeError:
            return None
    return a if isinstance(a, dict) else None


def _diff(exp: dict, actual: dict | None) -> list[str]:
    if actual is None:
        return ["参数不是合法的 JSON 对象"]
    out = []
    for k, v in exp.get("arguments", {}).items():
        got = actual.get(k, MISSING)
        if not values_equal(v, got):
            out.append(f"{k} 缺失（期望 {json.dumps(v, ensure_ascii=False)}）" if got is MISSING
                       else f"{k}：期望 {json.dumps(v, ensure_ascii=False)}，实际 {json.dumps(got, ensure_ascii=False)}")
    return out


def check_calls(expected: list[dict], actual: list[dict] | None, allow_extra: bool = False) -> str | None:
    """None if the calls match, else a short reason (Chinese, shown to people)."""
    actual = list(actual or [])
    if not actual:
        return "没有调用工具"
    unmatched, reasons = list(actual), []
    for e in expected:
        hit = next((a for a in unmatched if a.get("name") == e["name"] and not _diff(e, _args(a))), None)
        if hit is not None:
            unmatched.remove(hit)
            continue
        same_name = next((a for a in unmatched if a.get("name") == e["name"]), None)
        if same_name is None:
            reasons.append(f"没有调用 {e['name']}（调用了 {', '.join(str(a.get('name')) for a in actual)}）")
        else:
            reasons.append(f"{e['name']} 的参数不符：" + "；".join(_diff(e, _args(same_name))))
            unmatched.remove(same_name)
    if unmatched and not allow_extra and not reasons:
        reasons.append("多调用了工具：" + ", ".join(str(a.get("name")) for a in unmatched))
    return "；".join(reasons) or None


def expected_text(expected: list[dict]) -> str:
    return "\n".join(f"{e['name']}({json.dumps(e.get('arguments', {}), ensure_ascii=False)})" for e in expected)


def _user_text(row: dict) -> str:
    for m in row.get("messages") or []:
        if m.get("role") == "user":
            c = m.get("content")
            return c if isinstance(c, str) else " ".join(p.get("text", "") for p in c or [] if isinstance(p, dict))
    return ""


def ensure_pass_rate(db, run_id: int) -> None:
    """Give a custom tool-call run a headline that means something: the share of samples whose call passed.

    The engine's own main metric for these datasets is an F1 over "should a tool be called at all", which is 100 % even when a
    call is malformed or has wrong arguments, and which cannot be recomputed after the platform's argument check or a manual
    review. The pass rate is a plain mean of the per-sample scores, so the adjusted score works on it. Idempotent.
    """
    from sqlalchemy import delete, select, update

    from ..models import RunMetric, SampleResult

    db.execute(delete(RunMetric).where(RunMetric.run_id == run_id, RunMetric.key == "pass_rate"))
    by_sub: dict[str, list[float]] = {}
    for sub, score in db.execute(select(SampleResult.subset, SampleResult.score).where(SampleResult.run_id == run_id)):
        if score is not None:
            by_sub.setdefault(sub, []).append(score)
    if not by_sub:
        return
    db.execute(update(RunMetric).where(RunMetric.run_id == run_id, RunMetric.primary.is_(True)).values(primary=False))
    allv = [v for vs in by_sub.values() for v in vs]
    fields = dict(kind="quality", key="pass_rate", label="通过率", display_multiplier=100.0, display_unit="%", precision=1, direction="higher_is_better")
    db.add(RunMetric(run_id=run_id, subset="OVERALL", value=sum(allv) / len(allv), num=len(allv), primary=True, **fields))
    for sub, vs in by_sub.items():
        if sub:
            db.add(RunMetric(run_id=run_id, subset=sub, value=sum(vs) / len(vs), num=len(vs), primary=False, **fields))


def apply_tool_check(samples: list, dataset_rows: list[dict]) -> int:
    """Set auto_correct (False = argument check failed), auto_reason, target, final_correct on fc samples (ORM rows or dicts).

    Only samples the engine passed can be downgraded; the engine's verdict itself is never changed. Manual reviews stay.
    Returns how many samples were downgraded.
    """
    get = lambda s, k: s.get(k) if isinstance(s, dict) else getattr(s, k)

    def put(s, k, v):
        if isinstance(s, dict):
            s[k] = v
        else:
            setattr(s, k, v)

    downgraded = 0
    for s in samples:
        idx = get(s, "idx")
        row = dataset_rows[idx] if isinstance(idx, int) and 0 <= idx < len(dataset_rows) else None
        if row is None or "expected_calls" not in row or not (get(s, "question") or "").strip().startswith(_user_text(row).strip()):
            if get(s, "final_correct") is None:  # no expectation for this sample (or the row is not its own): the engine's verdict stands
                review = get(s, "review_correct")
                put(s, "final_correct", review if review is not None else get(s, "is_correct"))
            continue
        put(s, "target", expected_text(row["expected_calls"]))
        reason = None
        if get(s, "is_correct") is True and not get(s, "error"):
            reason = check_calls(row["expected_calls"], get(s, "tool_calls"), bool(row.get("allow_extra_calls")))
        put(s, "auto_correct", False if reason else None)
        put(s, "auto_reason", reason)
        review = get(s, "review_correct")
        put(s, "final_correct", review if review is not None else (False if reason else get(s, "is_correct")))
        downgraded += bool(reason)
    return downgraded
