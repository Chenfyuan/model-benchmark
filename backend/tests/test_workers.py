"""Several workers sharing one queue."""
import threading
import time
from datetime import timedelta

import pytest
from sqlalchemy import select, update

import app.worker as worker
from app.db import SessionLocal
from app.models import ModelEndpoint, Run, Worker, utcnow
from conftest import MODEL
from fake_engine import FakeAdapter


def new_model(client, name, **extra):
    r = client.post("/api/v1/models", json={**MODEL, "name": name, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def queue(client, model, dataset, n=1):
    return [client.post("/api/v1/runs", json={"model_ids": [model["id"]], "dataset_ids": [dataset["id"]]}).json()[0]["id"] for _ in range(n)]


def status(run_id):
    with SessionLocal() as db:
        return db.get(Run, run_id).status


def alive_worker(worker_id, host="otherhost", age=0):
    with SessionLocal() as db:
        db.add(Worker(id=worker_id, host=host, pid=1, heartbeat_at=utcnow() - timedelta(seconds=age)))
        db.commit()


# ------------------------------------------------------------------ claiming

def test_racing_workers_never_claim_the_same_run(client, vmcq_dataset):
    models = [new_model(client, f"m{i}") for i in range(6)]  # different models: no per-model limit in the way
    ids = [queue(client, m, vmcq_dataset)[0] for m in models]
    got, barrier = [], threading.Barrier(8)

    def go(k):
        barrier.wait()
        while (r := worker.claim_next(f"w{k}")) is not None:
            got.append((r, f"w{k}"))

    ts = [threading.Thread(target=go, args=(k,)) for k in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(r for r, _ in got) == sorted(ids)  # every run exactly once
    with SessionLocal() as db:
        assert {r.id: r.worker_id for r in db.scalars(select(Run))} == {r: w for r, w in got}


def test_one_run_per_model_by_default_and_configurable(client, model, vmcq_dataset):
    a, b, c = queue(client, model, vmcq_dataset, 3)
    assert worker.claim_next("w1") == a
    assert worker.claim_next("w2") is None  # same model already running: the others wait
    client.put(f"/api/v1/models/{model['id']}", json={"max_parallel_runs": 2})
    assert worker.claim_next("w2") == b
    assert worker.claim_next("w3") is None  # limit of 2 reached
    with SessionLocal() as db:
        db.execute(update(Run).where(Run.id == a).values(status="completed"))
        db.commit()
    assert worker.claim_next("w3") == c


def test_a_busy_model_does_not_block_other_models(client, model, vmcq_dataset):
    other = new_model(client, "other")
    a1, a2 = queue(client, model, vmcq_dataset, 2)
    (b1,) = queue(client, other, vmcq_dataset)
    assert worker.claim_next("w1") == a1
    assert worker.claim_next("w2") == b1  # a2 is skipped (its model is busy), b1 behind it is taken
    assert worker.claim_next("w3") is None and status(a2) == "queued"


def test_max_parallel_runs_is_validated_and_returned(client):
    assert client.post("/api/v1/models", json={**MODEL, "max_parallel_runs": 0}).status_code == 422
    m = new_model(client, "x", max_parallel_runs=3)
    assert m["max_parallel_runs"] == 3
    assert client.get(f"/api/v1/models/{m['id']}").json()["max_parallel_runs"] == 3


# ------------------------------------------------------------------ crash recovery

def test_runs_of_a_live_worker_are_left_alone_and_a_dead_ones_are_recovered(client, vmcq_dataset):
    m1, m2, m3 = (new_model(client, f"m{i}") for i in range(3))
    live, dead, legacy = (queue(client, m, vmcq_dataset)[0] for m in (m1, m2, m3))
    alive_worker("live:1:0")
    alive_worker("dead:1:0", age=600)
    assert [worker.claim_next("live:1:0"), worker.claim_next("dead:1:0"), worker.claim_next(None)] == [live, dead, legacy]
    assert worker.requeue_stale() == 2
    assert status(live) == "running" and status(dead) == "queued" and status(legacy) == "queued"
    with SessionLocal() as db:
        r = db.get(Run, dead)
        assert r.worker_id is None and r.resume is True  # continues from its finished samples


def test_only_one_worker_recovers_a_stale_run(client, model, vmcq_dataset):
    (rid,) = queue(client, model, vmcq_dataset)
    assert worker.claim_next("gone:1:0") == rid
    results, barrier = [], threading.Barrier(5)

    def go():
        barrier.wait()
        results.append(worker.requeue_stale())

    ts = [threading.Thread(target=go) for _ in range(5)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sum(results) == 1


def test_a_worker_that_lost_its_run_stops_and_writes_nothing(client, model, vmcq_dataset, tmp_path):
    (rid,) = queue(client, model, vmcq_dataset)
    assert worker.claim_next("slow:1:0") == rid
    out = {}
    t = threading.Thread(target=lambda: out.update(s=worker.process_run(rid, FakeAdapter("slow", n=10, delay=0.5, calls_file=str(tmp_path / "c")), worker_id="slow:1:0")))
    t.start()
    time.sleep(3)  # engine is up and answering
    assert worker.requeue_stale() == 1  # others decided this worker is dead (it never registered a heartbeat) ...
    assert worker.claim_next("fast:1:0") == rid  # ... and took the run over
    t.join(timeout=30)
    assert out["s"] == "lost"
    with SessionLocal() as db:
        r = db.get(Run, rid)
        assert r.status == "running" and r.worker_id == "fast:1:0" and r.error is None  # the new owner's state is untouched


def test_shutdown_hands_the_run_back_for_resuming(client, model, vmcq_dataset, tmp_path):
    (rid,) = queue(client, model, vmcq_dataset)
    assert worker.claim_next("w:1:0") == rid
    out = {}
    t = threading.Thread(target=lambda: out.update(s=worker.process_run(rid, FakeAdapter("slow", n=10, delay=0.5, calls_file=str(tmp_path / "c")), worker_id="w:1:0")))
    t.start()
    time.sleep(3)
    worker.SHUTDOWN.set()
    try:
        t.join(timeout=30)
    finally:
        worker.SHUTDOWN.clear()
    assert out["s"] == "requeued"
    with SessionLocal() as db:
        r = db.get(Run, rid)
        assert (r.status, r.worker_id, r.resume) == ("queued", None, True) and r.input_tokens > 0  # progress and billing kept
    # the next worker continues instead of starting over
    assert worker.claim_next("w2:1:0") == rid
    assert worker.process_run(rid, FakeAdapter("slow", n=10, delay=0.01, calls_file=str(tmp_path / "c")), worker_id="w2:1:0") == "completed"
    with SessionLocal() as db:
        r = db.get(Run, rid)
        assert r.reused_samples and r.reused_samples >= 1 and r.input_tokens == 10 * 1000


# ------------------------------------------------------------------ slots in one process, and status

def test_two_slots_process_two_runs_at_the_same_time(client, vmcq_dataset, tmp_path, monkeypatch):
    models = [new_model(client, f"m{i}") for i in range(3)]
    ids = [queue(client, m, vmcq_dataset)[0] for m in models]
    adapter = FakeAdapter("slow", n=6, delay=0.4, calls_file=str(tmp_path / "c"))
    monkeypatch.setattr(worker, "get_adapter", lambda _engine: adapter)
    monkeypatch.setenv("WORKER_POLL_SEC", "0.2")
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "worker_poll_sec", 0.2)
    slots = ["h:1:0", "h:1:1"]
    for s in slots:
        worker._register(s)
    ts = [threading.Thread(target=worker.slot_loop, args=(s,)) for s in slots]
    [t.start() for t in ts]
    peak = 0
    try:
        deadline = time.time() + 90
        while time.time() < deadline:
            with SessionLocal() as db:
                states = [r.status for r in db.scalars(select(Run))]
            peak = max(peak, states.count("running"))
            if states.count("completed") == 3:
                break
            time.sleep(0.2)
    finally:
        worker.SHUTDOWN.set()
        [t.join(timeout=30) for t in ts]
        worker.SHUTDOWN.clear()
    assert all(status(i) == "completed" for i in ids) and peak == 2


def test_workers_endpoint(client, model, vmcq_dataset):
    assert client.get("/api/v1/workers").json() == {"slots": [], "alive": 0, "idle": 0, "queued": 0, "running": 0}
    queue(client, model, vmcq_dataset, 2)
    alive_worker("a:1:0")
    alive_worker("b:1:0")
    alive_worker("old:1:0", age=600)
    worker.claim_next("a:1:0")
    with SessionLocal() as db:
        db.execute(update(Worker).where(Worker.id == "a:1:0").values(run_id=1))
        db.commit()
    w = client.get("/api/v1/workers").json()
    assert (w["alive"], w["idle"], w["queued"], w["running"]) == (2, 1, 1, 1)  # the stale slot is not counted
