from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    protocol: Literal["openai", "anthropic"]
    base_url: str = Field(min_length=8, max_length=500)
    model_name: str = Field(min_length=1, max_length=200)
    api_key: str = Field(min_length=1)
    price_input_per_mtok: float | None = Field(default=None, ge=0)
    price_output_per_mtok: float | None = Field(default=None, ge=0)

    @field_validator("base_url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip()
        if not v.lower().startswith(("http://", "https://")):
            raise ValueError("base_url 必须以 http:// 或 https:// 开头")
        return v


class ModelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    protocol: Literal["openai", "anthropic"] | None = None
    base_url: str | None = None
    model_name: str | None = None
    api_key: str | None = Field(default=None, min_length=1)  # omit to keep the stored key
    price_input_per_mtok: float | None = Field(default=None, ge=0)
    price_output_per_mtok: float | None = Field(default=None, ge=0)


class ModelOut(ORM):
    id: int
    name: str
    protocol: str
    base_url: str
    model_name: str
    api_key_hint: str  # never the key itself
    price_input_per_mtok: float | None
    price_output_per_mtok: float | None
    last_check: dict[str, Any] | None
    created_at: datetime


class DatasetOut(ORM):
    id: int
    name: str
    version: int
    source: str
    kind: str
    benchmark_id: str | None
    capability: str | None
    description: str
    verified: bool
    num_samples: int | None
    created_at: datetime


class RunCreate(BaseModel):
    model_ids: list[int] = Field(min_length=1)
    dataset_ids: list[int] = Field(min_length=1)
    judge_model_id: int | None = None
    limit: int | None = Field(default=None, ge=1)  # per subset; null = full set
    batch_size: int = Field(default=2, ge=1, le=64)
    max_tokens: int = Field(default=1024, ge=1)
    temperature: float = Field(default=0.0, ge=0, le=2)
    confirm_over_budget: bool = False  # proceed even though the estimate exceeds an optional limit


class RunOut(ORM):
    id: int
    model_id: int
    model_name: str
    dataset_id: int
    dataset_name: str
    dataset_version: int
    judge_model_id: int | None
    judge_model_name: str | None
    parent_run_id: int | None
    status: str
    stage: str
    progress: float
    error: str | None
    limit: int | None
    config: dict[str, Any]
    engine: str
    engine_version: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    attempts: int = 1
    reused_samples: int | None = None  # samples skipped on the latest retry because they were already finished
    input_tokens: int | None = None  # billed, cumulative over attempts
    output_tokens: int | None = None
    cost: float | None = None
    stop_reason: str | None = None  # budget_run | budget_month when a spending limit stopped the run
    headline: dict[str, Any] | None = None  # primary metric, for the run list


class MetricOut(ORM):
    kind: str
    key: str
    label: str
    subset: str
    value: float | None
    num: int | None
    display_multiplier: float
    display_unit: str
    precision: int
    direction: str
    primary: bool


class SampleOut(ORM):
    id: int
    idx: int
    subset: str
    question: str
    media: list[dict[str, Any]]
    target: str | None
    prediction: str | None
    extracted: str | None
    tool_calls: list[dict[str, Any]] | None
    scores: dict[str, Any]
    score: float | None
    is_correct: bool | None
    judge_output: str | None
    latency: float | None
    input_tokens: int | None
    output_tokens: int | None
    error: str | None


class EstimateIn(BaseModel):
    model_id: int
    dataset_id: int
    limit: int | None = Field(default=None, ge=1)


class Page(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int
