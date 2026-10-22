"""Seed a data directory with finished runs (no model is called): python e2e/seed.py <data_dir>

Two models answered the same 7 open questions; model-a's answers need lenient matching ("6.8%" for "6.8", ...).
Also leaves one queued run so the "no worker online" hint can be tested.
"""
import json
import sys
from pathlib import Path

DATA = Path(sys.argv[1]).resolve()
import os

os.environ["APP_DATA_DIR"] = str(DATA)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import update  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Run, RunMetric, SampleResult  # noqa: E402

ROWS = [("6.8", "6.8%"), ("1000", "1,000"), ("Paris", "paris"), ("cat", "dog"), ("42", "42"), ("12", "120"), ("blue", "Blue.")]
ANSWERS = {"model-a": [p for _, p in ROWS], "model-b": ["6.9", "999", "Rome", "dog", "42", "120", "red"]}

with TestClient(app) as c:
    body = "\n".join(json.dumps({"messages": [{"role": "user", "content": [{"type": "text", "text": f"问题 {i}"}]}], "answer": a}) for i, (a, _) in enumerate(ROWS))
    ds = c.post("/api/v1/datasets", data={"name": "图表问答-演示", "kind": "vqa", "capability": "doc_chart"}, files={"file": ("d.jsonl", body.encode())}).json()
    for name, preds in ANSWERS.items():
        m = c.post("/api/v1/models", json=dict(name=name, protocol="openai", base_url="http://127.0.0.1:9", model_name=name, api_key="sk-stub-0000")).json()
        rid = c.post("/api/v1/runs", json={"model_ids": [m["id"]], "dataset_ids": [ds["id"]]}).json()[0]["id"]
        ok = [a == p for (a, _), p in zip(ROWS, preds)]
        with SessionLocal() as db:
            db.execute(update(Run).where(Run.id == rid).values(status="completed", stage="done", engine_version="1.14.0"))
            for sub in ("OVERALL", "data"):
                db.add(RunMetric(run_id=rid, kind="quality", key="relaxed_acc", label="Accuracy", subset=sub, value=sum(ok) / len(ok), num=len(ok),
                                 display_multiplier=100.0, display_unit="%", precision=1, direction="higher_is_better", primary=sub == "OVERALL"))
            for i, ((a, _), p, k) in enumerate(zip(ROWS, preds, ok)):
                db.add(SampleResult(run_id=rid, idx=i, subset="data", question=f"问题 {i}", target=a, prediction=p, extracted=p, is_correct=k, score=float(k), latency=1.2))
            db.commit()
        c.post(f"/api/v1/runs/{rid}/rescore")
    queued = c.post("/api/v1/models", json=dict(name="model-c", protocol="openai", base_url="http://127.0.0.1:9", model_name="c", api_key="sk-stub-0000")).json()
    c.post("/api/v1/runs", json={"model_ids": [queued["id"]], "dataset_ids": [ds["id"]]})
print("seeded")
