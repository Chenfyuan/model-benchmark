"""Spending limits (optional, off by default) and retry-without-rebilling."""
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import update

from app.db import SessionLocal
from app.models import Run, utcnow
from app.worker import claim_next, process_run
from conftest import MODEL
from fake_engine import FakeAdapter

PER_SAMPLE_TOKENS = 1010  # the fake engine "bills" 1000 input + 10 output tokens per sample


@pytest.fixture
def priced_model(client):
    r = client.post("/api/v1/models", json={**MODEL, "price_input_per_mtok": 1.0, "price_output_per_mtok": 2.0})
    assert r.status_code == 201
    return r.json()


def new_run(client, model, dataset, **extra):
    r = client.post("/api/v1/runs", json={"model_ids": [model["id"]], "dataset_ids": [dataset["id"]], **extra})
    assert r.status_code == 201, r.text
    return r.json()[0]


def run_attempt(run_id, adapter):
    assert claim_next() == run_id
    return process_run(run_id, adapter)


def calls(path: Path) -> int:
    return len(path.read_text().split()) if path.exists() else 0


# ------------------------------------------------------------------ the limits API

def test_no_limits_by_default(client):
    b = client.get("/api/v1/settings/budget").json()
    assert all(v is None for v in b["limits"].values())
    assert b["usage"]["tokens"] == 0 and b["usage"]["month"]


def test_set_and_clear_limits(client, model):
    r = client.put("/api/v1/settings/budget", json={"per_run_max_tokens": 5000, "monthly_max_cost": 20.5}).json()
    assert r["limits"]["per_run_max_tokens"] == 5000 and r["limits"]["monthly_max_cost"] == 20.5
    assert r["limits"]["monthly_max_tokens"] is None
    assert "m1" in r["unpriced_models"]  # the money limit cannot apply to a model without a price
    r = client.put("/api/v1/settings/budget", json={"per_run_max_tokens": 0, "monthly_max_cost": None}).json()  # 0 / null = no limit
    assert all(v is None for v in r["limits"].values())
    assert client.put("/api/v1/settings/budget", json={"per_run_max_tokens": -1}).status_code == 422


# ------------------------------------------------------------------ submit-time check

def test_submit_over_budget_needs_confirmation(client, model, vmcq_dataset):
    client.put("/api/v1/settings/budget", json={"per_run_max_tokens": 100})
    body = {"model_ids": [model["id"]], "dataset_ids": [vmcq_dataset["id"]]}  # 2 samples ~ 10k estimated tokens
    r = client.post("/api/v1/runs", json=body)
    assert r.status_code == 409 and r.json()["code"] == "budget_exceeded"
    assert "单次上限" in r.json()["details"][0]
    assert client.get("/api/v1/runs").json()["total"] == 0  # nothing was created
    assert client.post("/api/v1/runs", json={**body, "confirm_over_budget": True}).status_code == 201


def test_submit_checks_the_monthly_limit_with_what_is_already_used(client, model, vmcq_dataset):
    run = new_run(client, model, vmcq_dataset)
    with SessionLocal() as db:
        db.execute(update(Run).where(Run.id == run["id"]).values(started_at=utcnow(), input_tokens=9000, output_tokens=500))
        db.commit()
    client.put("/api/v1/settings/budget", json={"monthly_max_tokens": 12000})
    r = client.post("/api/v1/runs", json={"model_ids": [model["id"]], "dataset_ids": [vmcq_dataset["id"]]})
    assert r.status_code == 409 and "月度上限" in r.json()["details"][0]
    assert client.get("/api/v1/settings/budget").json()["usage"]["tokens"] == 9500


def test_no_limits_means_no_checks(client, model, vmcq_dataset):
    assert client.post("/api/v1/runs", json={"model_ids": [model["id"]], "dataset_ids": [vmcq_dataset["id"]]}).status_code == 201


# ------------------------------------------------------------------ run-time enforcement + retry that reuses finished samples

def test_limit_stops_the_run_and_retry_resumes_without_rebilling(client, priced_model, vmcq_dataset, tmp_path):
    log = tmp_path / "calls.log"
    run = new_run(client, priced_model, vmcq_dataset)
    client.put("/api/v1/settings/budget", json={"per_run_max_tokens": 3500})  # reached after 4 samples

    assert run_attempt(run["id"], FakeAdapter("slow", n=10, delay=0.5, calls_file=str(log))) == "failed"
    r = client.get(f"/api/v1/runs/{run['id']}").json()
    assert r["status"] == "failed" and r["stop_reason"] == "budget_run"
    assert "单次上限" in r["error"] and "跳过" in r["error"] and "重发" in r["error"]  # incl. the in-flight caveat
    done = calls(log)
    assert 4 <= done < 10, done  # it really stopped part-way
    assert r["input_tokens"] == done * 1000 and r["output_tokens"] == done * 10
    assert r["cost"] == pytest.approx(done * (1000 * 1.0 + 10 * 2.0) / 1e6)

    client.put("/api/v1/settings/budget", json={"per_run_max_tokens": None})  # the admin raises (removes) the limit
    retried = client.post(f"/api/v1/runs/{run['id']}/retry").json()
    assert retried["status"] == "queued" and retried["attempts"] == 2 and retried["stop_reason"] is None

    assert run_attempt(run["id"], FakeAdapter("slow", n=10, delay=0.01, calls_file=str(log))) == "completed"
    r = client.get(f"/api/v1/runs/{run['id']}").json()
    assert r["status"] == "completed" and r["stop_reason"] is None
    assert r["reused_samples"] == done  # the samples that were already answered were not sent again
    assert calls(log) == 10  # every sample was requested exactly once across both attempts
    assert r["input_tokens"] == 10 * 1000 and r["output_tokens"] == 10 * 10  # billed once, cumulative over attempts
    assert r["cost"] == pytest.approx(10 * 1020 / 1e6)


def test_cancel_then_retry_also_resumes(client, priced_model, vmcq_dataset, tmp_path):
    log = tmp_path / "calls.log"
    run = new_run(client, priced_model, vmcq_dataset)
    assert claim_next() == run["id"]
    result = {}
    t = threading.Thread(target=lambda: result.update(s=process_run(run["id"], FakeAdapter("slow", n=10, delay=0.5, calls_file=str(log)))))
    t.start()
    deadline = time.time() + 30
    while time.time() < deadline and calls(log) < 3:
        time.sleep(0.2)
    client.post(f"/api/v1/runs/{run['id']}/cancel")
    t.join(30)
    assert result["s"] == "cancelled"
    done = calls(log)

    client.post(f"/api/v1/runs/{run['id']}/retry")
    assert run_attempt(run["id"], FakeAdapter("slow", n=10, delay=0.01, calls_file=str(log))) == "completed"
    r = client.get(f"/api/v1/runs/{run['id']}").json()
    assert r["reused_samples"] >= 3 and calls(log) == 10 and r["attempts"] == 2


def test_retry_without_any_finished_samples_starts_fresh(client, model, vmcq_dataset):
    run = new_run(client, model, vmcq_dataset)
    assert run_attempt(run["id"], FakeAdapter("fail")) == "failed"  # fails before writing any prediction
    client.post(f"/api/v1/runs/{run['id']}/retry")
    assert run_attempt(run["id"], FakeAdapter("fail")) == "failed"
    assert client.get(f"/api/v1/runs/{run['id']}").json()["reused_samples"] is None


def test_exhausted_monthly_budget_blocks_the_start(client, priced_model, vmcq_dataset, tmp_path):
    other = new_run(client, priced_model, vmcq_dataset)
    with SessionLocal() as db:
        db.execute(update(Run).where(Run.id == other["id"]).values(started_at=utcnow(), status="completed", input_tokens=900, output_tokens=200))
        db.commit()
    client.put("/api/v1/settings/budget", json={"monthly_max_tokens": 1000})
    run = new_run(client, priced_model, vmcq_dataset, confirm_over_budget=True)  # the submit-time check would stop us otherwise
    log = tmp_path / "calls.log"
    assert run_attempt(run["id"], FakeAdapter("slow", n=3, delay=0.01, calls_file=str(log))) == "failed"
    r = client.get(f"/api/v1/runs/{run['id']}").json()
    assert r["stop_reason"] == "budget_month" and "月度上限" in r["error"]
    assert calls(log) == 0  # the engine was never started


def test_money_limit_only_applies_to_priced_models(client, model, vmcq_dataset, tmp_path):
    """The default test model has no price, so a money limit cannot stop it (a token limit still can)."""
    client.put("/api/v1/settings/budget", json={"per_run_max_cost": 0.000001})
    log = tmp_path / "calls.log"
    run = new_run(client, model, vmcq_dataset)
    assert run_attempt(run["id"], FakeAdapter("slow", n=3, delay=0.05, calls_file=str(log))) == "completed"
    assert client.get(f"/api/v1/runs/{run['id']}").json()["cost"] is None
