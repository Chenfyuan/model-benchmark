"""Background worker: takes queued runs, runs the engine in a subprocess, stores normalised results.

Run with:  python -m app.worker
One run at a time per worker process. On start-up, runs left in `running` by a crashed worker are re-queued.
"""
from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

from sqlalchemy import delete, select, update

from .config import get_settings
from .crypto import decrypt, redact
from .db import SessionLocal, init_db
from .engines import get_adapter
from .engines.base import Endpoint, EngineAdapter, ParsedResult, RunContext
from .models import ModelEndpoint, Run, RunMetric, SampleResult, utcnow

log = logging.getLogger("worker")
LOG_TAIL_BYTES = 16000


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
        db.execute(delete(SampleResult).where(SampleResult.run_id == run_id))
        db.add_all(RunMetric(run_id=run_id, **m) for m in parsed.metrics)
        db.add_all(SampleResult(run_id=run_id, **s) for s in parsed.samples)
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


def process_run(run_id: int, adapter: EngineAdapter | None = None) -> str:
    """Execute one run that is already marked `running`. Returns the final status."""
    settings = get_settings()
    secrets: list[str] = []
    try:
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            adapter = adapter or get_adapter(run.engine)
            ctx = build_context(run)
        secrets = [ctx.model.api_key] + ([ctx.judge.api_key] if ctx.judge else [])

        shutil.rmtree(ctx.work_dir, ignore_errors=True)
        ctx.work_dir.mkdir(parents=True)
        prepared = adapter.prepare(ctx)

        with open(prepared.log_path, "wb") as logf:
            proc = subprocess.Popen(
                prepared.cmd, cwd=prepared.cwd, env=prepared.env, stdout=logf, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        _update(run_id, pid=proc.pid, stage="preparing")
        started = time.time()
        cancelled = timed_out = False
        last_stage: tuple[str, float | None] = ("preparing", None)
        while proc.poll() is None:
            time.sleep(1)
            with SessionLocal() as db:
                cancelled = bool(db.scalar(select(Run.cancel_requested).where(Run.id == run_id)))
            if cancelled:
                _terminate(proc)
                break
            if time.time() - started > settings.run_timeout_sec:
                timed_out = True
                _terminate(proc)
                break
            stage = adapter.progress(_read_tail(prepared.log_path))
            if stage != last_stage:
                last_stage = stage
                _update(run_id, stage=stage[0], progress=stage[1] or 0.0)

        log_text = _read_tail(prepared.log_path)
        if cancelled:
            _update(run_id, status="cancelled", stage="done", pid=None, finished_at=utcnow())
            return "cancelled"
        if timed_out:
            _update(run_id, status="failed", stage="done", pid=None, finished_at=utcnow(),
                    error=f"超过 {settings.run_timeout_sec} 秒的运行时间上限，已终止")
            return "failed"
        if proc.returncode != 0:
            _update(run_id, status="failed", stage="done", pid=None, finished_at=utcnow(),
                    error=error_summary(log_text, secrets) or f"引擎退出码 {proc.returncode}")
            return "failed"

        _update(run_id, stage="collecting", progress=1.0)
        save_results(run_id, adapter.collect(ctx))
        _update(run_id, status="completed", stage="done", pid=None, finished_at=utcnow(), error=None)
        return "completed"
    except Exception as e:  # noqa: BLE001  (never leave a run stuck in `running`)
        log.exception("run %s failed", run_id)
        _update(run_id, status="failed", stage="done", pid=None, finished_at=utcnow(),
                error=redact(f"{type(e).__name__}: {e}", secrets)[:2000])
        return "failed"


def claim_next() -> int | None:
    with SessionLocal() as db:
        run_id = db.scalar(select(Run.id).where(Run.status == "queued").order_by(Run.id).limit(1))
        if run_id is None:
            return None
        res = db.execute(
            update(Run).where(Run.id == run_id, Run.status == "queued").values(
                status="running", stage="preparing", progress=0.0, started_at=utcnow(), finished_at=None,
                error=None, cancel_requested=False,
            )
        )
        db.commit()
        return run_id if res.rowcount else None


def requeue_stale() -> int:
    with SessionLocal() as db:
        res = db.execute(update(Run).where(Run.status == "running").values(status="queued", stage="queued", pid=None))
        db.commit()
        return res.rowcount


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    init_db()
    n = requeue_stale()
    if n:
        log.info("re-queued %d run(s) left running by a previous worker", n)
    log.info("worker started")
    poll = get_settings().worker_poll_sec
    while True:
        run_id = claim_next()
        if run_id is None:
            time.sleep(poll)
            continue
        log.info("run %s started", run_id)
        log.info("run %s finished: %s", run_id, process_run(run_id))


if __name__ == "__main__":
    main()
