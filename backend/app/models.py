"""Database tables. See the design doc, section 6 (data model)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ModelEndpoint(Base):
    """A model under test (or a judge): somebody else's HTTP API."""

    __tablename__ = "model_endpoint"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    protocol: Mapped[str] = mapped_column(String(20))  # openai | anthropic
    base_url: Mapped[str] = mapped_column(String(500))
    model_name: Mapped[str] = mapped_column(String(200))
    api_key_enc: Mapped[str] = mapped_column(Text)
    api_key_hint: Mapped[str] = mapped_column(String(20))  # "****abcd"
    price_input_per_mtok: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_output_per_mtok: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_check: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # how many runs of this model may be evaluated at the same time (NULL = 1); each run already sends `batch_size` requests at once
    max_parallel_runs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # extra HTTP headers sent with every request to this model (e.g. a gateway's user-identity header); not secret, shown in the UI
    extra_headers: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)


class Dataset(Base):
    """An evaluation set: either a built-in public benchmark or an uploaded custom set (one row per version)."""

    __tablename__ = "dataset"
    __table_args__ = (UniqueConstraint("name", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer, default=1)
    source: Mapped[str] = mapped_column(String(20))  # builtin | custom
    kind: Mapped[str] = mapped_column(String(20))  # benchmark | vqa | vmcq | fc
    benchmark_id: Mapped[str | None] = mapped_column(String(100), nullable=True)  # EvalScope dataset id
    capability: Mapped[str | None] = mapped_column(String(30), nullable=True)  # doc_chart | general_qa | tool_call
    description: Mapped[str] = mapped_column(Text, default="")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)  # actually run end to end on this platform
    num_samples: Mapped[int | None] = mapped_column(Integer, nullable=True)
    path: Mapped[str | None] = mapped_column(String(500), nullable=True)  # directory holding data.jsonl
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    @property
    def needs_judge(self) -> bool:
        from .services.catalog import NEEDS_JUDGE

        return self.benchmark_id in NEEDS_JUDGE


class Run(Base):
    """One evaluation task: model x dataset x configuration."""

    __tablename__ = "run"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("model_endpoint.id"))
    dataset_id: Mapped[int] = mapped_column(ForeignKey("dataset.id"))
    judge_model_id: Mapped[int | None] = mapped_column(ForeignKey("model_endpoint.id"), nullable=True)
    parent_run_id: Mapped[int | None] = mapped_column(ForeignKey("run.id"), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    # queued | running | completed | failed | cancelled
    stage: Mapped[str] = mapped_column(String(30), default="queued")
    # queued | preparing | downloading | evaluating | collecting | done
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0..1, from the engine's progress bar
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    # Everything below is nullable so databases created before these columns existed keep working (see db.ensure_columns).
    attempts: Mapped[int | None] = mapped_column(Integer, nullable=True, default=1)  # 1 + number of retries
    resume: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False)  # next start reuses finished samples
    reused_samples: Mapped[int | None] = mapped_column(Integer, nullable=True)  # samples skipped thanks to the cache
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)  # billed, cumulative over attempts
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)  # None when the model has no price set
    stop_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)  # budget_run | budget_month
    worker_id: Mapped[str | None] = mapped_column(String(100), nullable=True)  # the worker slot that owns this run while it is running
    auto_retries: Mapped[int | None] = mapped_column(Integer, nullable=True)  # automatic re-queues after provider errors (reset by a manual retry)
    retry_after: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # queued runs wait until this time (back-off)

    limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # snapshot of everything that affects scores
    engine: Mapped[str] = mapped_column(String(30), default="evalscope")
    engine_version: Mapped[str | None] = mapped_column(String(30), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    model: Mapped[ModelEndpoint] = relationship(foreign_keys=[model_id])
    judge_model: Mapped[ModelEndpoint | None] = relationship(foreign_keys=[judge_model_id])
    dataset: Mapped[Dataset] = relationship()


class RunMetric(Base):
    __tablename__ = "run_metric"
    __table_args__ = (Index("ix_run_metric_run", "run_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))  # quality | diagnostic | perf
    key: Mapped[str] = mapped_column(String(100))  # engine's metric name, e.g. relaxed_acc
    label: Mapped[str] = mapped_column(String(100))  # human label, e.g. Accuracy
    subset: Mapped[str] = mapped_column(String(100))  # OVERALL or a subset name
    value: Mapped[float | None] = mapped_column(Float, nullable=True)  # raw value (ratios are 0..1)
    num: Mapped[int | None] = mapped_column(Integer, nullable=True)
    display_multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    display_unit: Mapped[str] = mapped_column(String(20), default="")
    precision: Mapped[int] = mapped_column(Integer, default=2)
    direction: Mapped[str] = mapped_column(String(30), default="none")  # higher_is_better | lower_is_better | none
    primary: Mapped[bool] = mapped_column(Boolean, default=False)  # the benchmark's headline metric


class SampleResult(Base):
    __tablename__ = "sample_result"
    __table_args__ = (Index("ix_sample_run_correct", "run_id", "is_correct"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"))
    idx: Mapped[int] = mapped_column(Integer)
    subset: Mapped[str] = mapped_column(String(100), default="")
    question: Mapped[str] = mapped_column(Text, default="")
    media: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # [{"type": "image", "kind": "file"|"url", "ref": "<relative path or url>"}]
    target: Mapped[str | None] = mapped_column(Text, nullable=True)
    prediction: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    scores: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)  # main score of this sample
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # score >= 1
    judge_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency: Mapped[float | None] = mapped_column(Float, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Review layer (all nullable: see services/rescoring.py). is_correct/score above stay the engine's verdict.
    auto_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # lenient re-check says right
    auto_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # a person's decision
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    final_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # review > lenient > engine


class Worker(Base):
    """One worker slot (a worker process runs `WORKER_CONCURRENCY` of them). Alive = recent heartbeat."""

    __tablename__ = "worker"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)  # host:pid:slot
    host: Mapped[str] = mapped_column(String(100))
    pid: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # the run it is working on, if any


class ScoreScheme(Base):
    """A saved way of combining scores over several datasets into one number (weights chosen by the team)."""

    __tablename__ = "score_scheme"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)  # [{"dataset_name": str, "weight": float > 0}]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Setting(Base):
    """Small key/value store for platform-wide settings (currently only the budget limits)."""

    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
