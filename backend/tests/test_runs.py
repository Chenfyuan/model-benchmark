import threading
import time

import pytest
from PIL import Image
from sqlalchemy import update

from app.db import SessionLocal
from app.models import Run, SampleResult
from app.worker import claim_next, process_run, requeue_stale
from conftest import MODEL
from fake_engine import FakeAdapter


@pytest.fixture
def imgdir(tmp_path):
    d = tmp_path / "imgs"
    d.mkdir()
    for i in range(6):
        Image.new("RGB", (8, 8), (255, 0, 0)).save(d / f"img{i}.png")
    return str(d)


def make_run(client, model, dataset, **extra):
    r = client.post("/api/v1/runs", json={"model_ids": [model["id"]], "dataset_ids": [dataset["id"]], **extra})
    assert r.status_code == 201, r.text
    return r.json()[0]


def run_to_end(run_id, adapter):
    assert claim_next() == run_id
    return process_run(run_id, adapter)


def test_run_completes_and_results_are_stored(client, model, vmcq_dataset, imgdir):
    run = make_run(client, model, vmcq_dataset, limit=20)
    assert run["status"] == "queued" and run["config"]["max_tokens"] == 1024
    assert run_to_end(run["id"], FakeAdapter(imgdir=imgdir)) == "completed"

    r = client.get(f"/api/v1/runs/{run['id']}").json()
    assert r["status"] == "completed" and r["progress"] == 1.0 and r["engine_version"]
    assert r["headline"]["label"] == "Accuracy" and r["headline"]["display"] == "100.0%"
    assert r["started_at"] and r["finished_at"] and r["error"] is None

    metrics = client.get(f"/api/v1/runs/{run['id']}/metrics").json()
    assert {m["kind"] for m in metrics} >= {"quality", "perf"}

    page = client.get(f"/api/v1/runs/{run['id']}/samples").json()
    assert page["total"] == 2
    s = page["items"][0]
    assert s["media"][0]["kind"] == "file" and s["is_correct"] is True and s["latency"] > 0
    img = client.get(f"/api/v1/runs/{run['id']}/samples/{s['id']}/media/0")
    assert img.status_code == 200 and img.content[:4] == b"\x89PNG"

    assert client.get(f"/api/v1/runs/{run['id']}/samples", params={"correct": "false"}).json()["total"] == 0
    assert client.get(f"/api/v1/runs/{run['id']}/samples", params={"q": "background color"}).json()["total"] == 2
    csv_text = client.get(f"/api/v1/runs/{run['id']}/export").text
    assert csv_text.lstrip("﻿").startswith("idx,subset,question") and csv_text.count("\n") >= 3
    assert "Evaluating" in client.get(f"/api/v1/runs/{run['id']}/log").text


def test_list_runs_filters_and_pages(client, model, vmcq_dataset):
    for _ in range(3):
        make_run(client, model, vmcq_dataset)
    page = client.get("/api/v1/runs", params={"page_size": 2}).json()
    assert page["total"] == 3 and len(page["items"]) == 2 and page["items"][0]["id"] > page["items"][1]["id"]
    assert client.get("/api/v1/runs", params={"status": "completed"}).json()["total"] == 0


def test_failed_run_error_hides_the_key(client, model, vmcq_dataset):
    run = make_run(client, model, vmcq_dataset)
    assert run_to_end(run["id"], FakeAdapter("fail")) == "failed"
    r = client.get(f"/api/v1/runs/{run['id']}").json()
    assert r["status"] == "failed" and "boom" in r["error"]
    assert "sk-secret-1234" not in r["error"] and "***" in r["error"]
    assert "sk-secret-1234" not in client.get(f"/api/v1/runs/{run['id']}/log").text


def test_secrets_not_written_to_run_directory(client, model, vmcq_dataset, imgdir):
    from app.worker import run_dir

    run = make_run(client, model, vmcq_dataset)
    run_to_end(run["id"], FakeAdapter(imgdir=imgdir))
    for f in run_dir(run["id"]).rglob("*"):
        if f.is_file() and f.suffix in (".json", ".jsonl", ".log", ".txt"):
            assert "sk-secret-1234" not in f.read_text(errors="ignore"), f


def test_cancel_running_run(client, model, vmcq_dataset):
    run = make_run(client, model, vmcq_dataset)
    assert claim_next() == run["id"]
    result = {}
    t = threading.Thread(target=lambda: result.update(status=process_run(run["id"], FakeAdapter("sleep"))))
    t.start()
    deadline = time.time() + 20
    while time.time() < deadline:
        cur = client.get(f"/api/v1/runs/{run['id']}").json()
        if cur["stage"] == "downloading":  # the fake engine's log says it is downloading
            break
        time.sleep(0.3)
    assert cur["status"] == "running" and cur["stage"] == "downloading"
    assert client.post(f"/api/v1/runs/{run['id']}/cancel").json()["status"] == "running"  # request accepted, worker acts on it
    t.join(30)
    assert not t.is_alive() and result["status"] == "cancelled"
    final = client.get(f"/api/v1/runs/{run['id']}").json()
    assert final["status"] == "cancelled" and final["finished_at"]


def test_cancel_queued_then_retry(client, model, vmcq_dataset):
    run = make_run(client, model, vmcq_dataset)
    assert client.post(f"/api/v1/runs/{run['id']}/cancel").json()["status"] == "cancelled"
    assert client.post(f"/api/v1/runs/{run['id']}/cancel").status_code == 409
    assert client.post(f"/api/v1/runs/{run['id']}/retry").json()["status"] == "queued"
    assert client.post(f"/api/v1/runs/{run['id']}/retry").status_code == 409  # only failed / cancelled runs


def test_retry_clears_old_results(client, model, vmcq_dataset, imgdir):
    run = make_run(client, model, vmcq_dataset)
    run_to_end(run["id"], FakeAdapter(imgdir=imgdir))
    with SessionLocal() as db:
        db.execute(update(Run).where(Run.id == run["id"]).values(status="failed"))
        db.commit()
    client.post(f"/api/v1/runs/{run['id']}/retry")
    assert client.get(f"/api/v1/runs/{run['id']}/samples").json()["total"] == 0
    assert client.get(f"/api/v1/runs/{run['id']}/metrics").json() == []


def test_rerun_copies_configuration(client, model, vmcq_dataset):
    run = make_run(client, model, vmcq_dataset, limit=7, temperature=0.3, max_tokens=64)
    new = client.post(f"/api/v1/runs/{run['id']}/rerun").json()
    assert new["id"] != run["id"] and new["parent_run_id"] == run["id"]
    assert new["limit"] == 7 and new["config"]["temperature"] == 0.3 and new["config"]["max_tokens"] == 64
    assert new["dataset_id"] == run["dataset_id"] and new["status"] == "queued"


def test_stale_running_runs_are_requeued(client, model, vmcq_dataset):
    run = make_run(client, model, vmcq_dataset)
    assert claim_next() == run["id"]
    assert client.get(f"/api/v1/runs/{run['id']}").json()["status"] == "running"
    assert requeue_stale() == 1
    assert client.get(f"/api/v1/runs/{run['id']}").json()["status"] == "queued"


def test_idempotency_key(client, model, vmcq_dataset):
    body = {"model_ids": [model["id"]], "dataset_ids": [vmcq_dataset["id"]]}
    a = client.post("/api/v1/runs", json=body, headers={"Idempotency-Key": "k1"}).json()
    b = client.post("/api/v1/runs", json=body, headers={"Idempotency-Key": "k1"}).json()
    assert [r["id"] for r in a] == [r["id"] for r in b]
    assert client.get("/api/v1/runs").json()["total"] == 1


def test_models_times_datasets(client, model, vmcq_dataset):
    m2 = client.post("/api/v1/models", json={**MODEL, "name": "m2"}).json()
    builtin = client.get("/api/v1/datasets", params={"source": "builtin"}).json()[0]
    r = client.post("/api/v1/runs", json={"model_ids": [model["id"], m2["id"]], "dataset_ids": [vmcq_dataset["id"], builtin["id"]]})
    assert len(r.json()) == 4


def test_judge_must_use_openai_protocol(client, model, vmcq_dataset):
    anth = client.post("/api/v1/models", json={**MODEL, "name": "anth", "protocol": "anthropic"}).json()
    r = client.post("/api/v1/runs", json={"model_ids": [model["id"]], "dataset_ids": [vmcq_dataset["id"]], "judge_model_id": anth["id"]})
    assert r.status_code == 400 and r.json()["code"] == "judge_protocol"


def test_unknown_ids_are_404(client, model, vmcq_dataset):
    assert client.post("/api/v1/runs", json={"model_ids": [999], "dataset_ids": [vmcq_dataset["id"]]}).status_code == 404
    assert client.get("/api/v1/runs/999").status_code == 404


def test_media_endpoint_refuses_paths_outside_the_run_directory(client, model, vmcq_dataset, imgdir):
    run = make_run(client, model, vmcq_dataset)
    run_to_end(run["id"], FakeAdapter(imgdir=imgdir))
    with SessionLocal() as db:
        s = db.query(SampleResult).filter_by(run_id=run["id"]).first()
        s.media = [{"type": "image", "kind": "file", "ref": "../../secret.key"}]
        db.commit()
        sid = s.id
    assert client.get(f"/api/v1/runs/{run['id']}/samples/{sid}/media/0").status_code == 404


def test_sample_filters_on_wrong_and_error(client, model, vmcq_dataset):
    run = make_run(client, model, vmcq_dataset)
    with SessionLocal() as db:
        db.add_all([
            SampleResult(run_id=run["id"], idx=1, subset="a", question="q1", is_correct=True, score=1.0),
            SampleResult(run_id=run["id"], idx=2, subset="a", question="q2", is_correct=False, score=0.0),
            SampleResult(run_id=run["id"], idx=3, subset="b", question="q3", is_correct=None, error="failed"),
        ])
        db.commit()
    total = lambda **p: client.get(f"/api/v1/runs/{run['id']}/samples", params=p).json()["total"]  # noqa: E731
    assert (total(), total(correct="true"), total(correct="false"), total(correct="error"), total(subset="b")) == (3, 1, 1, 1, 1)
    assert client.get(f"/api/v1/runs/{run['id']}/samples", params={"correct": "maybe"}).status_code == 422


def test_csv_export_neutralises_formulas(client, model, vmcq_dataset):
    run = make_run(client, model, vmcq_dataset)
    with SessionLocal() as db:
        db.add(SampleResult(run_id=run["id"], idx=1, subset="a", question="=HYPERLINK(\"http://evil\")", is_correct=False))
        db.commit()
    text = client.get(f"/api/v1/runs/{run['id']}/export").text
    assert "'=HYPERLINK" in text and ",=HYPERLINK" not in text


def test_estimate(client, model, vmcq_dataset):
    client.put(f"/api/v1/models/{model['id']}", json={"price_input_per_mtok": 3.0, "price_output_per_mtok": 15.0})
    e = client.post("/api/v1/runs/estimate", json={"model_id": model["id"], "dataset_id": vmcq_dataset["id"]}).json()
    assert e["num_samples"] == 2 and e["token_source"] == "default"
    assert e["cost"] == pytest.approx(2 * (5000 * 3.0 + 150 * 15.0) / 1e6)
    e = client.post("/api/v1/runs/estimate", json={"model_id": model["id"], "dataset_id": vmcq_dataset["id"], "limit": 1}).json()
    assert e["num_samples"] == 1

    builtin = client.get("/api/v1/datasets", params={"source": "builtin"}).json()[0]
    e = client.post("/api/v1/runs/estimate", json={"model_id": model["id"], "dataset_id": builtin["id"]}).json()
    assert e["num_samples"] is None and e["cost"] is None and e["notes"]


def test_estimate_uses_history(client, model, vmcq_dataset, imgdir):
    run = make_run(client, model, vmcq_dataset)
    run_to_end(run["id"], FakeAdapter(imgdir=imgdir))
    e = client.post("/api/v1/runs/estimate", json={"model_id": model["id"], "dataset_id": vmcq_dataset["id"]}).json()
    assert e["token_source"] == "history" and e["avg_input_tokens"] != 5000


def test_delete_run_removes_everything(client, model, vmcq_dataset, imgdir):
    from app.worker import run_dir

    run = make_run(client, model, vmcq_dataset)
    run_to_end(run["id"], FakeAdapter(imgdir=imgdir))
    assert client.delete(f"/api/v1/runs/{run['id']}").status_code == 204
    assert client.get(f"/api/v1/runs/{run['id']}").status_code == 404
    assert not run_dir(run["id"]).exists()
