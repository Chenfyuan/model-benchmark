from __future__ import annotations

import importlib.metadata
import json
import os
import re
import sys
from pathlib import Path

from ..services.model_check import anthropic_base, openai_base
from .base import ParsedResult, Prepared, RunContext, Usage
from .evalscope_results import latest_output_dir, parse_report, parse_reviews

BACKEND_DIR = Path(__file__).resolve().parents[2]
_EVAL_BAR = re.compile(r"Evaluating\[[^\]]*\]:\s*(\d+)%\|[^|]*\|\s*(\d+)/(\d+)")

CUSTOM_DATASETS = {"vqa": "general_vqa", "vmcq": "general_vmcq", "fc": "general_fc"}


def output_dirs(out_root: Path) -> list[Path]:
    """EvalScope output directories (one per timestamp) that already hold predictions, oldest first."""
    if not out_root.is_dir():
        return []
    return sorted(d for d in out_root.iterdir() if d.is_dir() and (d / "predictions").is_dir())


class PredictionUsage:
    """Incrementally sums model_output.usage over EvalScope's prediction files (verified: written one line per answered
    sample, before scoring). With a resumed run the newest directory holds the cached and the new predictions together,
    so its total is exactly what has been billed across all attempts."""

    def __init__(self, out_root: Path):
        self.out_root = out_root
        self.dir: Path | None = None
        self.files: dict[Path, tuple[int, int, int, int]] = {}  # path -> (offset, input, output, samples)

    def poll(self) -> Usage:
        dirs = output_dirs(self.out_root)
        newest = dirs[-1] if dirs else None
        if newest != self.dir:
            self.dir, self.files = newest, {}
        if newest is None:
            return Usage()
        for f in (newest / "predictions").rglob("*.jsonl"):
            off, i, o, n = self.files.get(f, (0, 0, 0, 0))
            try:
                with open(f, "rb") as fh:
                    fh.seek(off)
                    chunk = fh.read()
            except OSError:
                continue
            end = chunk.rfind(b"\n") + 1  # never parse a half-written last line
            for line in chunk[:end].splitlines():
                try:
                    usage = (json.loads(line).get("model_output") or {}).get("usage") or {}
                except ValueError:
                    continue
                i += int(usage.get("input_tokens") or 0)
                o += int(usage.get("output_tokens") or 0)
                n += 1
            self.files[f] = (off + end, i, o, n)
        return Usage(sum(v[1] for v in self.files.values()), sum(v[2] for v in self.files.values()), sum(v[3] for v in self.files.values()))


class EvalScopeAdapter:
    name = "evalscope"

    def prepare(self, ctx: RunContext) -> Prepared:
        m = ctx.model
        eval_type = "openai_api" if m.protocol == "openai" else "anthropic_api"
        api_url = openai_base(m.base_url) if m.protocol == "openai" else anthropic_base(m.base_url)

        if ctx.dataset_kind == "benchmark":
            datasets, dataset_args = [ctx.benchmark_id], {}
        else:
            name = CUSTOM_DATASETS[ctx.dataset_kind]
            datasets = [name]
            dataset_args = {name: {"local_path": ctx.dataset_path, "subset_list": ["data"]}}

        cfg = {
            "model": m.model_name,
            "api_url": api_url,
            "eval_type": eval_type,
            "datasets": datasets,
            "dataset_args": dataset_args,
            "limit": ctx.limit,
            "work_dir": str(ctx.work_dir / "out"),
            "generation_config": {"max_tokens": ctx.max_tokens, "temperature": ctx.temperature},
            "eval_batch_size": ctx.batch_size,
        }
        if ctx.resume_from:
            cfg["use_cache"] = str(ctx.resume_from)
        env = dict(os.environ)
        env["EVAL_API_KEY"] = m.api_key
        env["PYTHONPATH"] = str(BACKEND_DIR) + os.pathsep + env.get("PYTHONPATH", "")
        if ctx.judge:
            cfg["judge"] = {"model_id": ctx.judge.model_name, "api_url": openai_base(ctx.judge.base_url)}
            env["JUDGE_API_KEY"] = ctx.judge.api_key

        ctx.work_dir.mkdir(parents=True, exist_ok=True)
        cfg_path = ctx.work_dir / "task.json"
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        return Prepared(
            cmd=[sys.executable, "-m", "app.engines.evalscope_task", str(cfg_path)],
            env=env,
            cwd=BACKEND_DIR,
            log_path=ctx.work_dir / "engine.log",
        )

    def resumable(self, ctx: RunContext) -> tuple[Path, int] | None:
        dirs = output_dirs(ctx.work_dir / "out")
        if not dirs:
            return None
        samples = PredictionUsage(ctx.work_dir / "out").poll().samples  # the tracker reads the newest directory
        return (dirs[-1], samples) if samples else None

    def usage_tracker(self, ctx: RunContext) -> PredictionUsage:
        return PredictionUsage(ctx.work_dir / "out")

    def progress(self, log_tail: str) -> tuple[str, float | None]:
        tail = log_tail.replace("\r", "\n")
        bar = None
        for bar in _EVAL_BAR.finditer(tail):
            pass
        dl = tail.rfind("Downloading")
        if dl != -1 and (bar is None or dl > bar.start()):
            return "downloading", None
        if bar is not None:
            done, total = int(bar.group(2)), int(bar.group(3))
            return "evaluating", (done / total if total else None)
        return "preparing", None

    def collect(self, ctx: RunContext) -> ParsedResult:
        out = latest_output_dir(ctx.work_dir / "out")
        reports = sorted((out / "reports").rglob("*.json"))
        if not reports:
            raise FileNotFoundError("EvalScope produced no report file")
        report = json.loads(reports[0].read_text(encoding="utf-8"))
        samples = parse_reviews(out / "reviews", report.get("dataset_name", ""), ctx.work_dir / "media")
        try:
            version = importlib.metadata.version("evalscope")
        except importlib.metadata.PackageNotFoundError:
            version = None
        return ParsedResult(engine_version=version, metrics=parse_report(report), samples=samples)
