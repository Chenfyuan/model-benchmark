from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass
class Endpoint:
    protocol: str  # openai | anthropic
    base_url: str
    model_name: str
    api_key: str


@dataclass
class RunContext:
    """Everything an engine needs for one run, as plain data (no ORM objects, no DB access)."""

    run_id: int
    work_dir: Path
    model: Endpoint
    dataset_kind: str  # benchmark | vqa | vmcq | fc
    benchmark_id: str | None
    dataset_path: str | None
    judge: Endpoint | None = None
    limit: int | None = None
    batch_size: int = 2
    max_tokens: int = 1024
    temperature: float = 0.0


@dataclass
class Prepared:
    cmd: list[str]
    env: dict[str, str]
    cwd: Path
    log_path: Path


@dataclass
class ParsedResult:
    engine_version: str | None = None
    metrics: list[dict[str, Any]] = field(default_factory=list)
    samples: list[dict[str, Any]] = field(default_factory=list)


class EngineAdapter(Protocol):
    name: str

    def prepare(self, ctx: RunContext) -> Prepared:
        """Translate a run into an engine process (config file + command). Secrets go in `env`, never on disk."""

    def progress(self, log_tail: str) -> tuple[str, float | None]:
        """Return (stage, progress 0..1 or None) from the tail of the engine's log."""

    def collect(self, ctx: RunContext) -> ParsedResult:
        """Parse the engine's output files into the platform's own metric / sample format."""
