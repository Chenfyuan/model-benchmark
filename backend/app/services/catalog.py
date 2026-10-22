"""Built-in public benchmarks (EvalScope dataset ids) grouped by the three first-phase capabilities.

`verified` means the benchmark was actually run end to end through this platform's engine
(design doc, section 12.1). The rest come from EvalScope's published list and have not been run here.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Dataset

CAPABILITIES = {"doc_chart": "文档图表", "general_qa": "通用问答", "tool_call": "工具调用"}

# Benchmarks whose score comes entirely from an LLM judge: without a judge model the engine refuses to start.
NEEDS_JUDGE = {"charxiv"}

BUILTIN: list[dict] = [
    # document / chart
    dict(benchmark_id="chartqa", name="ChartQA", capability="doc_chart", verified=True, description="图表问答"),
    dict(benchmark_id="docvqa", name="DocVQA", capability="doc_chart", verified=True, description="文档页面问答（指标为 Similarity）"),
    dict(benchmark_id="infovqa", name="InfoVQA", capability="doc_chart", description="信息图问答"),
    dict(benchmark_id="ocr_bench", name="OCRBench", capability="doc_chart", description="文字识别"),
    dict(benchmark_id="charxiv", name="CharXiv", capability="doc_chart", description="科研论文图表理解（必须配裁判模型）"),
    dict(benchmark_id="ai2d", name="AI2D", capability="doc_chart", description="科学图示问答"),
    # general QA
    dict(benchmark_id="mm_bench", name="MMBench", capability="general_qa", verified=True, description="通用多模态选择题（中英文）"),
    dict(benchmark_id="mmmu", name="MMMU", capability="general_qa", description="大学水平多学科多模态问答"),
    dict(benchmark_id="mm_star", name="MMStar", capability="general_qa", description="视觉依赖型多模态问答"),
    dict(benchmark_id="real_world_qa", name="RealWorldQA", capability="general_qa", description="真实场景图片问答"),
    dict(benchmark_id="seed_bench_2_plus", name="SEED-Bench-2-Plus", capability="general_qa", description="文本丰富场景的选择题"),
    dict(benchmark_id="vqav2", name="VQAv2", capability="general_qa", description="通用视觉问答"),
    # tool calling (only text-only function calling is covered; no BFCL / tau-bench in EvalScope's list)
    dict(benchmark_id="tool_bench", name="ToolBench-Static", capability="tool_call", description="工具调用（静态评测）"),
]


def seed_builtin(db: Session) -> None:
    """Insert missing built-in benchmarks; idempotent."""
    existing = {d.benchmark_id for d in db.scalars(select(Dataset).where(Dataset.source == "builtin"))}
    for b in BUILTIN:
        if b["benchmark_id"] in existing:
            continue
        db.add(
            Dataset(
                name=b["name"], version=1, source="builtin", kind="benchmark", benchmark_id=b["benchmark_id"],
                capability=b["capability"], description=b["description"], verified=b.get("verified", False),
            )
        )
    db.commit()
