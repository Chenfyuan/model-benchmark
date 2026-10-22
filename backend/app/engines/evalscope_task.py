"""Subprocess entry point: run one EvalScope task described by a JSON file.

Usage: python -m app.engines.evalscope_task <task.json>
API keys come from the environment (EVAL_API_KEY, JUDGE_API_KEY), never from the JSON file.
"""
from __future__ import annotations

import json
import os
import sys


def main(path: str) -> None:
    from evalscope import TaskConfig, run_task

    cfg = json.load(open(path, encoding="utf-8"))
    kwargs = dict(
        model=cfg["model"],
        api_url=cfg["api_url"],
        api_key=os.environ["EVAL_API_KEY"],
        eval_type=cfg["eval_type"],
        datasets=cfg["datasets"],
        work_dir=cfg["work_dir"],
        generation_config=cfg["generation_config"],
        eval_batch_size=cfg["eval_batch_size"],
    )
    if cfg.get("dataset_args"):
        kwargs["dataset_args"] = cfg["dataset_args"]
    if cfg.get("limit"):
        kwargs["limit"] = cfg["limit"]
    if cfg.get("use_cache"):
        kwargs["use_cache"] = cfg["use_cache"]  # continue from a previous output dir: finished samples are not re-sent
    if cfg.get("judge"):
        kwargs["judge_strategy"] = "llm"
        kwargs["judge_model_args"] = {**cfg["judge"], "api_key": os.environ["JUDGE_API_KEY"]}
    run_task(task_cfg=TaskConfig(**kwargs))


if __name__ == "__main__":
    main(sys.argv[1])
