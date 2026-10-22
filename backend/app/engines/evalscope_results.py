"""Parse EvalScope output (verified against EvalScope 1.14.0, design doc section 12.1).

<out>/<timestamp>/reports/<model>/<dataset>.json          aggregate report
<out>/<timestamp>/reviews/<model>/<dataset>_<subset>.jsonl  one line per sample
"""
from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path
from typing import Any

MAX_TEXT = 20000
MAX_MEDIA_BYTES = 20 * 1024 * 1024
MIME_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}


def latest_output_dir(out_root: Path) -> Path:
    dirs = sorted(d for d in out_root.iterdir() if d.is_dir() and (d / "reports").is_dir())
    if not dirs:
        raise FileNotFoundError(f"EvalScope produced no reports under {out_root}")
    return dirs[-1]


# ---------------------------------------------------------------- aggregate report

def parse_report(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    primary_taken = False
    for m in report.get("metrics", []):
        sem = m.get("semantics") or {}
        base = dict(
            kind=sem.get("kind") or "quality",
            key=(m.get("identity") or {}).get("name", "metric"),
            label=sem.get("metric_name") or (m.get("identity") or {}).get("name", "metric"),
            display_multiplier=sem.get("display_multiplier") or 1.0,
            display_unit=sem.get("display_unit") or "",
            precision=sem.get("display_precision", 2) if sem.get("display_precision") is not None else 2,
            direction=sem.get("direction") or "none",
        )
        is_primary = base["kind"] == "quality" and not primary_taken
        primary_taken = primary_taken or is_primary
        rows.append({**base, "subset": "OVERALL", "value": m.get("score"), "num": m.get("num"), "primary": is_primary})
        for cat in m.get("categories", []):
            for sub in cat.get("subsets", []):
                if sub.get("is_aggregate"):
                    continue
                rows.append({**base, "subset": sub.get("name", ""), "value": sub.get("score"), "num": sub.get("num"), "primary": False})

    perf = (report.get("perf_metrics") or {}).get("summary") or {}

    def add(key: str, label: str, value: Any, unit: str = "", precision: int = 2, direction: str = "none"):
        if value is not None:
            rows.append(dict(kind="perf", key=key, label=label, subset="OVERALL", value=value, num=perf.get("n_samples"),
                             display_multiplier=1.0, display_unit=unit, precision=precision, direction=direction, primary=False))

    lat = perf.get("latency") or {}
    add("latency_mean", "平均延迟", lat.get("mean"), "s", 2, "lower_is_better")
    add("latency_p50", "延迟 P50", lat.get("50%"), "s", 2, "lower_is_better")
    add("latency_p90", "延迟 P90", lat.get("90%"), "s", 2, "lower_is_better")
    add("latency_max", "最大延迟", lat.get("max"), "s", 2, "lower_is_better")
    usage = perf.get("usage") or {}
    add("input_tokens_mean", "平均输入 token", (usage.get("input_tokens") or {}).get("mean"), "", 0)
    add("output_tokens_mean", "平均输出 token", (usage.get("output_tokens") or {}).get("mean"), "", 0)
    add("total_input_tokens", "输入 token 合计", usage.get("total_input_tokens"), "", 0)
    add("total_output_tokens", "输出 token 合计", usage.get("total_output_tokens"), "", 0)
    add("output_tps", "输出吞吐", (perf.get("throughput") or {}).get("avg_output_tps"), "tok/s", 1)
    return rows


# ---------------------------------------------------------------- per-sample reviews

def _clip(s: Any) -> str | None:
    if s is None:
        return None
    s = s if isinstance(s, str) else json.dumps(s, ensure_ascii=False)
    return s if len(s) <= MAX_TEXT else s[:MAX_TEXT] + "…"


def main_score(score: dict[str, Any]) -> float | None:
    value = score.get("value")
    if not isinstance(value, dict):
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    for key in ("passed", score.get("main_score_name"), "acc", "accuracy"):
        if key and key in value and isinstance(value[key], (bool, int, float)):
            return float(value[key])
    for v in value.values():
        if isinstance(v, (bool, int, float)):
            return float(v)
    return None


def _store_media(part: dict[str, Any], kind: str, media_dir: Path, stem: str) -> dict[str, Any]:
    value = part.get(kind)
    if not isinstance(value, str):
        return {"type": kind, "kind": "missing", "ref": ""}
    media_dir.mkdir(parents=True, exist_ok=True)  # created lazily: most runs of text-only data never need it
    if value.startswith("data:"):
        header, _, b64 = value.partition(",")
        mime = header[5:].split(";")[0]
        try:
            raw = base64.b64decode(b64)
        except ValueError:
            return {"type": kind, "kind": "missing", "ref": "invalid base64"}
        if len(raw) > MAX_MEDIA_BYTES:
            return {"type": kind, "kind": "missing", "ref": "too large"}
        name = stem + MIME_EXT.get(mime, ".bin")
        (media_dir / name).write_bytes(raw)
        return {"type": kind, "kind": "file", "ref": f"media/{name}"}
    if value.startswith(("http://", "https://")):
        return {"type": kind, "kind": "url", "ref": value}
    src = Path(value)
    if src.is_file() and src.stat().st_size <= MAX_MEDIA_BYTES:
        name = stem + (src.suffix or ".bin")
        shutil.copyfile(src, media_dir / name)
        return {"type": kind, "kind": "file", "ref": f"media/{name}"}
    return {"type": kind, "kind": "missing", "ref": value[:120]}


def judge_text(model_output: Any) -> str | None:
    """The judge's reply as readable text. EvalScope stores the judge's whole API response (a dict or its JSON string)."""
    obj = model_output
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except json.JSONDecodeError:
            return obj  # already plain text
    try:
        text = obj["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return _clip(model_output)
    if not isinstance(text, str):  # content blocks
        text = "".join(b.get("text", "") for b in text if isinstance(b, dict)) if isinstance(text, list) else str(text)
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(data, dict) and ("verdict" in data or "reasoning" in data):
        verdict = f"结论：{data['verdict']}\n" if "verdict" in data else ""
        return (verdict + str(data.get("reasoning", ""))).strip()
    return text


def parse_review_row(row: dict[str, Any], subset: str, media_dir: Path) -> dict[str, Any]:
    idx = row.get("index", 0)
    question_parts: list[str] = []
    media: list[dict[str, Any]] = []
    assistant: dict[str, Any] = {}
    for msg in row.get("messages", []):
        if msg.get("role") == "assistant":
            assistant = msg
            continue
        content = msg.get("content")
        if isinstance(content, str):
            question_parts.append(content)
            continue
        for part in content or []:
            ptype = part.get("type")
            if ptype == "text":
                question_parts.append(part.get("text") or "")
            elif ptype in ("image", "video", "audio"):
                media.append(_store_media(part, ptype, media_dir, f"{subset}_{idx}_{len(media)}".replace("/", "_")))

    sample_score = row.get("sample_score") or {}
    score = sample_score.get("score") or {}
    value = main_score(score)
    perf = assistant.get("perf_metrics") or {}
    target = row.get("target")
    attempts = (score.get("metadata") or {}).get("judge_attempts") or []
    tool_calls = [
        {"name": (tc.get("function") or {}).get("name"), "arguments": (tc.get("function") or {}).get("arguments")}
        for tc in (assistant.get("tool_calls") or [])
    ] or None
    status = score.get("status")
    reply = assistant.get("content") if isinstance(assistant.get("content"), str) else ""
    # When the model answered with a tool call, EvalScope's own "prediction" text just echoes the question plus a
    # rendering of the call; the structured `tool_calls` above is the real answer.
    prediction = reply or (None if tool_calls else score.get("prediction"))
    return dict(
        idx=idx,
        subset=subset,
        question=_clip("\n".join(p for p in question_parts if p)) or "",
        media=media,
        target=_clip(", ".join(map(str, target)) if isinstance(target, list) else target),
        prediction=_clip(prediction),
        extracted=None if (tool_calls and not reply) else _clip(score.get("extracted_prediction")),
        tool_calls=tool_calls,
        scores=score.get("value") if isinstance(score.get("value"), dict) else {},
        score=value,
        is_correct=None if value is None else value >= 1.0,
        judge_output=_clip(judge_text(attempts[0].get("model_output"))) if attempts else None,
        latency=perf.get("latency"),
        input_tokens=perf.get("input_tokens"),
        output_tokens=perf.get("output_tokens"),
        error=None if status in (None, "success") else str(status),
    )


def parse_reviews(reviews_dir: Path, dataset_name: str, media_dir: Path) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    prefix = f"{dataset_name}_"
    for f in sorted(reviews_dir.rglob("*.jsonl")):
        subset = f.stem[len(prefix):] if f.stem.startswith(prefix) else f.stem
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    samples.append(parse_review_row(json.loads(line), subset, media_dir))
    return samples
