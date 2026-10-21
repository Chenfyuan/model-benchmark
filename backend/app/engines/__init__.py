"""Evaluation engine adapters.

The platform talks to engines only through `EngineAdapter` (design doc, section 8.1), so an engine can be
upgraded or swapped without touching the API, the database schema or the front end.
"""
from __future__ import annotations

from .base import EngineAdapter


def get_adapter(name: str) -> EngineAdapter:
    if name == "evalscope":
        from .evalscope_adapter import EvalScopeAdapter

        return EvalScopeAdapter()
    raise ValueError(f"unknown engine: {name}")
