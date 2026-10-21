from __future__ import annotations

import importlib.metadata
import json
import os
import re
import sys
from pathlib import Path

from ..services.model_check import anthropic_base, openai_base
from .base import ParsedResult, Prepared, RunContext
from .evalscope_results import latest_output_dir, parse_report, parse_reviews

BACKEND_DIR = Path(__file__).resolve().parents[2]
_EVAL_BAR = re.compile(r"Evaluating\[[^\]]*\]:\s*(\d+)%\|[^|]*\|\s*(\d+)/(\d+)")

CUSTOM_DATASETS = {"vqa": "general_vqa", "vmcq": "general_vmcq", "fc": "general_fc"}


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
