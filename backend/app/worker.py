"""Background worker: takes queued runs, runs the engine in a subprocess, stores normalised results.

Run with:  python -m app.worker        (WORKER_CONCURRENCY=N handles N runs at once; start more processes to scale out)

Any number of workers, on any number of machines sharing the database and data directory, may run at once:
  * a run is claimed with one atomic UPDATE, so two workers never take the same run;
  * a model's runs are limited to `ModelEndpoint.max_parallel_runs` (default 1) at a time, so the provider is not flooded;
  * every worker slot heartbeats; a run whose worker stopped heartbeating is re-queued by the others and continues from
    its finished samples (the orphaned engine process is killed if it is on this host);
  * on SIGTERM a worker stops taking work, stops its engines and re-queues its runs (they resume where they were).
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import signal
import socket
import subprocess
import threading
import time
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import aliased

from .config import get_settings
from .crypto import decrypt, redact
from .db import SessionLocal, init_db
from .engines import get_adapter
from .engines.base import Endpoint, EngineAdapter, ParsedResult, RunContext, Usage
from .models import ModelEndpoint, Run, RunMetric, SampleResult, Worker, utcnow
from .services.rescoring import apply_lenient, load_dataset_rows
from .services.tool_check import apply_tool_check
from .services.budget import check as check_budget
from .services.budget import get_budget, month_usage, run_cost

log = logging.getLogger("worker")
LOG_TAIL_BYTES = 16000
# Errors that come from the provider's side and usually go away: worth re-queuing instead of failing the run.
TRANSIENT = re.compile(
    r"Error code: (?:429|5\d\d)|RateLimitError|InternalServerError|APIConnectionError|APITimeoutError|ServiceUnavailable|"
    r"Connection (?:reset|aborted|refused)|Read timed out|ReadTimeout|ConnectTimeout|overloaded", re.I)
SHUTDOWN = threading.Event()  # set on SIGTERM / SIGINT: stop claiming, hand running runs back to the queue
HEARTBEAT_SEC = 5


def _endpoint(m: ModelEndpoint) -> Endpoint:
    return Endpoint(protocol=m.protocol, base_url=m.base_url, model_name=m.model_name, api_key=decrypt(m.api_key_enc))


def run_dir(run_id: int) -> Path:
    return get_settings().runs_dir / str(run_id)


def build_context(run: Run) -> RunContext:
    cfg = run.config or {}
    ds = run.dataset
    return RunContext(
        run_id=run.id,
        work_dir=run_dir(run.id),
        model=_endpoint(run.model),
        judge=_endpoint(run.judge_model) if run.judge_model else None,
        dataset_kind=ds.kind,
        benchmark_id=ds.benchmark_id,
        dataset_path=ds.path,
        limit=run.limit,
        batch_size=cfg.get("batch_size", 2),
        max_tokens=cfg.get("max_tokens", 1024),
        temperature=cfg.get("temperature", 0.0),
    )


def _update(run_id: int, **fields) -> None:
    with SessionLocal() as db:
        db.execute(update(Run).where(Run.id == run_id).values(**fields))
        db.commit()


def _read_tail(path: Path) -> str:
    if not path.exists():
        return ""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - LOG_TAIL_BYTES))
        return f.read().decode("utf-8", errors="replace")


def error_summary(log_text: str, secrets: list[str]) -> str:
    lines = [ln.strip() for ln in log_text.replace("\r", "\n").splitlines() if ln.strip()]
    lines = [ln for ln in lines if "it/s]" not in ln and "s/it]" not in ln and "B/s]" not in ln]
    tb = [i for i, ln in enumerate(lines) if ln.startswith("Traceback")]
    picked = lines[tb[-1]:][-6:] if tb else lines[-6:]
    return redact("\n".join(picked), secrets)[:2000]


def save_results(run_id: int, parsed: ParsedResult) -> None:
    with SessionLocal() as db:
        db.execute(delete(RunMetric).where(RunMetric.run_id == run_id))
        run = db.get(Run, run_id)
        judged, ds = bool(run.judge_model_id), run.dataset
        # a retry re-collects every sample: keep a person's decisions for answers that did not change
        kept = {(r.subset, r.idx): r for r in db.scalars(select(SampleResult).where(SampleResult.run_id == run_id, SampleResult.review_correct.is_not(None)))}
        kept = {k: (r.prediction, r.review_correct, r.review_note, r.reviewed_at) for k, r in kept.items()}
        db.execute(delete(SampleResult).where(SampleResult.run_id == run_id))
        db.add_all(RunMetric(run_id=run_id, **m) for m in parsed.metrics)
        for s in parsed.samples:
            old = kept.get((s["subset"], s["idx"]))
            if old and old[0] == s["prediction"]:
                s["review_correct"], s["review_note"], s["reviewed_at"] = old[1:]
            if judged or ds.kind == "fc":  # a judge decides meaning itself; tool calls get the argument check below, not string matching
                review = s.get("review_correct")
                s.update(auto_correct=None, auto_reason=None, final_correct=s["is_correct"] if review is None else review)
            else:
                apply_lenient(s)
        if ds.kind == "fc" and not judged:
            apply_tool_check(parsed.samples, load_dataset_rows(ds.path))  # expectations in the dataset, if any: argument values
        for s in parsed.samples:
            db.add(SampleResult(run_id=run_id, **s))
        db.execute(update(Run).where(Run.id == run_id).values(engine_version=parsed.engine_version))
        db.commit()


def _terminate(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        proc.wait()
    except ProcessLookupError:
        pass


def _budget_stop(run_id: int, usage: Usage, cost: float | None, in_flight: int = 1) -> tuple[str, str] | None:
    """(stop_reason, message) if this run's usage breaks an optional spending limit. By default there are no limits."""
    with SessionLocal() as db:
        limits = get_budget(db)
        if not limits.any:
            return None
        month = month_usage(db, exclude_run_id=run_id)
    verdict = check_budget(limits, usage.input_tokens + usage.output_tokens, cost, month["tokens"], month["cost"])
    if verdict is None:
        return None
    reason, message = verdict
    keep = f"已完成的 {usage.samples} 题的结果还在，调高上限后点“重试”会跳过它们，不会重复计费。" if usage.samples else ""
    # stopping kills the engine: requests in flight at that moment (at most the concurrency) were already sent to the model
    # but produced no result, so they are neither counted in the usage above nor reused by a retry.
    lost = f"停止时正在进行的请求（最多 {in_flight} 个）可能已经发给模型，但没有结果，不计入上面的用量，重试时会重发。"
    return reason, f"{message}，已停止。{keep}{lost}"


def process_run(run_id: int, adapter: EngineAdapter | None = None, worker_id: str | None = None) -> str:
    """Execute one run that is already marked `running`. Returns the final status.

    With a `worker_id` the run must stay owned by that worker; if another worker has taken it over (this one looked dead)
    the engine is stopped and nothing more is written (returns "lost"). Returns "requeued" on shutdown.
    """
    settings = get_settings()
    secrets: list[str] = []
    try:
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            adapter = adapter or get_adapter(run.engine)
            ctx = build_context(run)
            resume = bool(run.resume)
            prices = (run.model.price_input_per_mtok, run.model.price_output_per_mtok)
            stored = Usage(run.input_tokens or 0, run.output_tokens or 0)
        secrets = [ctx.model.api_key] + ([ctx.judge.api_key] if ctx.judge else [])

        # A retry continues from the previous attempt's output, so samples that were already answered (and paid for)
        # are not sent again. Anything else starts from a clean directory.
        ctx.work_dir.mkdir(parents=True, exist_ok=True)
        previous = adapter.resumable(ctx) if resume else None
        for child in ctx.work_dir.iterdir():
            if previous and child.name == "out":
                continue
            shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink(missing_ok=True)
        ctx.resume_from = previous[0] if previous else None
        _update(run_id, resume=False, reused_samples=previous[1] if previous else None,
                **({} if previous else {"input_tokens": None, "output_tokens": None, "cost": None}))
        if not previous:
            stored = Usage()

        # Do not even start if a limit is already used up (e.g. the month's budget is spent).
        stop = _budget_stop(run_id, stored, run_cost(*prices, stored.input_tokens, stored.output_tokens), ctx.batch_size)
        if stop:
            _update(run_id, status="failed", stage="done", pid=None, finished_at=utcnow(), stop_reason=stop[0], error=stop[1])
            return "failed"

        prepared = adapter.prepare(ctx)
        with open(prepared.log_path, "wb") as logf:
            proc = subprocess.Popen(
                prepared.cmd, cwd=prepared.cwd, env=prepared.env, stdout=logf, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        _update(run_id, pid=proc.pid, stage="preparing")
        tracker = adapter.usage_tracker(ctx)
        started = time.time()
        cancelled = timed_out = lost = shutdown = stalled = False
        stop = None
        last_stage: tuple[str, float | None] = ("preparing", None)
        last_usage: tuple[int, int] = (-1, -1)
        tick = 0
        last_activity: tuple | None = None
        idle_since = time.time()

        def sync_usage() -> tuple[Usage, float | None]:
            """Persist billed usage whenever it changed; returns (usage, money spent or None if the model has no price)."""
            nonlocal last_usage
            usage = tracker.poll()
            cost = run_cost(*prices, usage.input_tokens, usage.output_tokens)
            if (usage.input_tokens, usage.output_tokens) != last_usage:
                last_usage = (usage.input_tokens, usage.output_tokens)
                _update(run_id, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens, cost=cost)
            return usage, cost

        while proc.poll() is None:
            time.sleep(1)
            tick += 1
            with SessionLocal() as db:
                cancelled, owner, status = db.execute(select(Run.cancel_requested, Run.worker_id, Run.status).where(Run.id == run_id)).one()
            if worker_id and (owner != worker_id or status != "running"):
                lost = True
                _terminate(proc)
                break
            if SHUTDOWN.is_set():
                shutdown = True
                _terminate(proc)
                break
            if cancelled:
                _terminate(proc)
                break
            if time.time() - started > settings.run_timeout_sec:
                timed_out = True
                _terminate(proc)
                break
            usage, cost = sync_usage()
            stop = _budget_stop(run_id, usage, cost, ctx.batch_size)
            if stop:
                _terminate(proc)
                break
            stage = adapter.progress(_read_tail(prepared.log_path))
            if stage != last_stage:
                last_stage = stage
                _update(run_id, stage=stage[0], progress=stage[1] or 0.0)
            # No new answer and no progress for a long time (not while downloading data: that is slow but fine) means the
            # provider is hanging; stop instead of waiting for the overall time limit.
            activity = (usage.input_tokens, usage.output_tokens, stage)
            if activity != last_activity:
                last_activity, idle_since = activity, time.time()
            elif settings.stall_timeout_sec and stage[0] != "downloading" and time.time() - idle_since > settings.stall_timeout_sec:
                stalled = True
                _terminate(proc)
                break

        if lost:
            log.warning("run %s was taken over by another worker; this one stops", run_id)
            return "lost"
        usage, cost = sync_usage()  # whatever the engine managed to write before it stopped
        if shutdown:
            _update(run_id, status="queued", stage="queued", pid=None, worker_id=None, resume=True)
            return "requeued"
        log_text = _read_tail(prepared.log_path)
        if cancelled:
            _update(run_id, status="cancelled", stage="done", pid=None, finished_at=utcnow())
            return "cancelled"
        if stop:
            final = _budget_stop(run_id, usage, cost, ctx.batch_size) or stop  # recomputed with the usage written up to the kill
            _update(run_id, status="failed", stage="done", pid=None, finished_at=utcnow(), stop_reason=final[0], error=final[1])
            return "failed"
        if stalled:
            msg = f"评测超过 {settings.stall_timeout_sec // 60} 分钟没有任何进展（没有新的回答），服务商可能卡住了，已终止"
            if _auto_retry(run_id, msg):
                return "retrying"
            _update(run_id, status="failed", stage="done", pid=None, finished_at=utcnow(), error=msg)
            return "failed"
        if timed_out:
            _update(run_id, status="failed", stage="done", pid=None, finished_at=utcnow(),
                    error=f"超过 {settings.run_timeout_sec} 秒的运行时间上限，已终止")
            return "failed"
        if proc.returncode != 0:
            summary = error_summary(log_text, secrets) or f"引擎退出码 {proc.returncode}"
            if TRANSIENT.search(log_text) and _auto_retry(run_id, summary):
                return "retrying"
            _update(run_id, status="failed", stage="done", pid=None, finished_at=utcnow(), error=summary)
            return "failed"

        _update(run_id, stage="collecting", progress=1.0)
        save_results(run_id, adapter.collect(ctx))
        _update(run_id, status="completed", stage="done", pid=None, finished_at=utcnow(), error=None, stop_reason=None)
        return "completed"
    except Exception as e:  # noqa: BLE001  (never leave a run stuck in `running`)
        log.exception("run %s failed", run_id)
        _update(run_id, status="failed", stage="done", pid=None, finished_at=utcnow(),
                error=redact(f"{type(e).__name__}: {e}", secrets)[:2000])
        return "failed"


def _auto_retry(run_id: int, summary: str) -> bool:
    """Put a run that hit a provider error back in the queue with back-off; it continues from its finished samples."""
    cfg = get_settings()
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        used = run.auto_retries or 0
        if used >= cfg.auto_retry_max:
            return False
        delay = cfg.auto_retry_base_sec * 2 ** used
        last = summary.strip().splitlines()[-1][:200] if summary.strip() else ""
        run.status, run.stage, run.pid, run.worker_id, run.resume = "queued", "queued", None, None, True
        run.attempts, run.auto_retries = (run.attempts or 1) + 1, used + 1
        run.retry_after = utcnow() + timedelta(seconds=delay)
        run.error = f"服务商返回了临时错误，{delay} 秒后自动重试（第 {used + 1}/{cfg.auto_retry_max} 次），已答完的样本不会重做。最后一条错误：{last}"
        db.commit()
    return True


def claim_next(worker_id: str | None = None) -> int | None:
    """Atomically take the oldest queued run whose model has a free slot. Returns its id, or None."""
    running = aliased(Run)
    with SessionLocal() as db:
        ready = or_(Run.retry_after.is_(None), Run.retry_after <= utcnow())  # runs backing off after a provider error wait
        candidates = db.scalars(select(Run.id).where(Run.status == "queued", ready).order_by(Run.id).limit(50)).all()
        for run_id in candidates:
            in_use = select(func.count()).select_from(running).where(running.model_id == Run.model_id, running.status == "running").correlate(Run).scalar_subquery()
            allowed = func.coalesce(select(ModelEndpoint.max_parallel_runs).where(ModelEndpoint.id == Run.model_id).correlate(Run).scalar_subquery(), 1)
            res = db.execute(
                update(Run).where(Run.id == run_id, Run.status == "queued", ready, in_use < allowed).values(
                    status="running", stage="preparing", progress=0.0, started_at=utcnow(), finished_at=None,
                    error=None, cancel_requested=False, worker_id=worker_id, retry_after=None,
                )
            )
            db.commit()
            if res.rowcount:  # lost the race for this one, or its model is busy: try the next candidate
                return run_id
        return None


def _kill_orphan(run_id: int, pid: int | None, host: str | None) -> None:
    """The engine of a run whose worker died may still be running (it has its own session). Kill it if it is ours to kill."""
    if not pid or host != socket.gethostname():
        return
    try:  # pids get reused: only touch a process that is demonstrably this run's engine
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            if str(run_dir(run_id)) not in f.read().decode(errors="replace"):  # the engine is started with <run dir>/task.json
                return
        os.killpg(pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass


def requeue_stale(stale_sec: int | None = None) -> int:
    """Hand back running runs whose worker is gone (no recent heartbeat, or an old single-worker row with no owner).

    They continue from the samples already answered. Safe to call from every worker at any time.
    """
    stale_sec = get_settings().worker_stale_sec if stale_sec is None else stale_sec
    n = 0
    with SessionLocal() as db:
        alive = set(db.scalars(select(Worker.id).where(Worker.heartbeat_at > utcnow() - timedelta(seconds=stale_sec))))
        hosts = dict(db.execute(select(Worker.id, Worker.host)).all())
        for run_id, owner, pid in db.execute(select(Run.id, Run.worker_id, Run.pid).where(Run.status == "running")).all():
            if owner is not None and owner in alive:
                continue
            res = db.execute(update(Run).where(Run.id == run_id, Run.status == "running", Run.worker_id.is_(owner) if owner is None else Run.worker_id == owner)
                             .values(status="queued", stage="queued", pid=None, worker_id=None, resume=True))
            db.commit()
            if res.rowcount:
                n += 1
                _kill_orphan(run_id, pid, hosts.get(owner))
        db.execute(delete(Worker).where(Worker.heartbeat_at < utcnow() - timedelta(days=1)))
        db.commit()
    return n


def _register(worker_id: str) -> None:
    with SessionLocal() as db:
        db.merge(Worker(id=worker_id, host=socket.gethostname(), pid=os.getpid(), started_at=utcnow(), heartbeat_at=utcnow(), run_id=None))
        db.commit()


def _heartbeat(worker_ids: list[str]) -> None:
    with SessionLocal() as db:
        db.execute(update(Worker).where(Worker.id.in_(worker_ids)).values(heartbeat_at=utcnow()))
        db.commit()


def _set_current(worker_id: str, run_id: int | None) -> None:
    with SessionLocal() as db:
        db.execute(update(Worker).where(Worker.id == worker_id).values(run_id=run_id, heartbeat_at=utcnow()))
        db.commit()


def slot_loop(worker_id: str) -> None:
    """One worker slot: claim a run, process it, repeat until shutdown."""
    poll = get_settings().worker_poll_sec
    while not SHUTDOWN.is_set():
        try:
            requeue_stale()
            run_id = claim_next(worker_id)
        except Exception:  # noqa: BLE001  (a database hiccup must not kill the slot)
            log.exception("%s: could not claim a run", worker_id)
            SHUTDOWN.wait(poll)
            continue
        if run_id is None:
            SHUTDOWN.wait(poll)
            continue
        _set_current(worker_id, run_id)
        log.info("%s: run %s started", worker_id, run_id)
        try:
            log.info("%s: run %s finished: %s", worker_id, run_id, process_run(run_id, worker_id=worker_id))
        finally:
            _set_current(worker_id, None)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    init_db()
    n = get_settings().worker_concurrency
    ids = [f"{socket.gethostname()}:{os.getpid()}:{k}" for k in range(n)]
    for w in ids:
        _register(w)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: SHUTDOWN.set())
    threads = [threading.Thread(target=slot_loop, args=(w,), name=w) for w in ids]
    for t in threads:
        t.start()
    log.info("worker started: %d slot(s)", n)
    while any(t.is_alive() for t in threads):
        try:
            _heartbeat(ids)
        except Exception:  # noqa: BLE001
            log.exception("heartbeat failed")
        SHUTDOWN.wait(HEARTBEAT_SEC)
    with SessionLocal() as db:
        db.execute(delete(Worker).where(Worker.id.in_(ids)))
        db.commit()
    log.info("worker stopped")


if __name__ == "__main__":
    main()
