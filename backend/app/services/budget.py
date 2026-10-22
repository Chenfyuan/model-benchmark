"""Optional spending limits. By default nothing is limited; an admin may set any of the four limits.

Limits are in tokens (always known) and/or money (only for models that have a price set). A month is a UTC calendar month.
Without logins, "confirm over budget" is a speed bump against mistakes, not a security control.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Run, Setting, utcnow

KEY = "budget"
FIELDS = ("per_run_max_tokens", "per_run_max_cost", "monthly_max_tokens", "monthly_max_cost")


@dataclass
class Budget:
    per_run_max_tokens: float | None = None
    per_run_max_cost: float | None = None
    monthly_max_tokens: float | None = None
    monthly_max_cost: float | None = None

    @property
    def any(self) -> bool:
        return any(v is not None for v in asdict(self).values())


def get_budget(db: Session) -> Budget:
    row = db.get(Setting, KEY)
    data = (row.value if row else {}) or {}
    return Budget(**{k: (data.get(k) if data.get(k) not in ("", 0) else None) for k in FIELDS})


def set_budget(db: Session, data: dict) -> Budget:
    clean = {k: (float(data[k]) if data.get(k) not in (None, "", 0) else None) for k in FIELDS}
    row = db.get(Setting, KEY)
    if row:
        row.value = clean
    else:
        db.add(Setting(key=KEY, value=clean))
    db.commit()
    return get_budget(db)


def month_start(now: datetime | None = None) -> datetime:
    now = now or utcnow()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def month_usage(db: Session, exclude_run_id: int | None = None) -> dict:
    q = select(
        func.coalesce(func.sum(func.coalesce(Run.input_tokens, 0) + func.coalesce(Run.output_tokens, 0)), 0),
        func.coalesce(func.sum(func.coalesce(Run.cost, 0.0)), 0.0),
        func.count(Run.id),
    ).where(Run.started_at >= month_start())
    if exclude_run_id is not None:
        q = q.where(Run.id != exclude_run_id)
    tokens, cost, n = db.execute(q).one()
    return {"month": month_start().strftime("%Y-%m"), "tokens": int(tokens), "cost": float(cost), "runs": int(n)}


def run_cost(price_in: float | None, price_out: float | None, input_tokens: int, output_tokens: int) -> float | None:
    """Money spent, or None when the model has no price (money limits then cannot apply to it)."""
    if price_in is None or price_out is None:
        return None
    return (input_tokens * price_in + output_tokens * price_out) / 1e6


def _fmt(tokens: float | None = None, cost: float | None = None) -> str:
    if tokens is not None:
        return f"{int(tokens):,} token"
    return f"{cost:,.4f}".rstrip("0").rstrip(".") if cost is not None else "?"


def check(budget: Budget, tokens: int, cost: float | None, month_tokens: int, month_cost: float) -> tuple[str, str] | None:
    """Return (stop_reason, human message) if this run's usage breaks a limit, else None.

    `tokens`/`cost` are this run's usage; `month_*` is everyone else's usage this month.
    """
    if budget.per_run_max_tokens is not None and tokens > budget.per_run_max_tokens:
        return "budget_run", f"这次评测已用 {_fmt(tokens)}，超过单次上限 {_fmt(budget.per_run_max_tokens)}"
    if budget.per_run_max_cost is not None and cost is not None and cost > budget.per_run_max_cost:
        return "budget_run", f"这次评测已花约 {_fmt(cost=cost)}，超过单次上限 {_fmt(cost=budget.per_run_max_cost)}"
    if budget.monthly_max_tokens is not None and month_tokens + tokens > budget.monthly_max_tokens:
        return "budget_month", f"本月累计已用 {_fmt(month_tokens + tokens)}，超过月度上限 {_fmt(budget.monthly_max_tokens)}"
    if budget.monthly_max_cost is not None and cost is not None and month_cost + cost > budget.monthly_max_cost:
        return "budget_month", f"本月累计已花约 {_fmt(cost=month_cost + cost)}，超过月度上限 {_fmt(cost=budget.monthly_max_cost)}"
    return None
