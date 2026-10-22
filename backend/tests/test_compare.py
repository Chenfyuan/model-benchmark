import pytest
from sqlalchemy import update

from app.db import SessionLocal
from app.models import Run, RunMetric, SampleResult
from conftest import MODEL


def make_run(client, model, dataset, **extra):
    r = client.post("/api/v1/runs", json={"model_ids": [model["id"]], "dataset_ids": [dataset["id"]], **extra})
    assert r.status_code == 201, r.text
    return r.json()[0]


def complete(run_id, accuracy, verdicts, subset="demo", engine_version="1.14.0"):
    """Mark a run completed with a headline metric and one sample per verdict (True / False / None)."""
    with SessionLocal() as db:
        db.execute(update(Run).where(Run.id == run_id).values(status="completed", engine_version=engine_version))
        db.add(RunMetric(run_id=run_id, kind="quality", key="accuracy", label="Accuracy", subset="OVERALL", value=accuracy, num=len(verdicts),
                         display_multiplier=100.0, display_unit="%", precision=1, direction="higher_is_better", primary=True))
        db.add(RunMetric(run_id=run_id, kind="quality", key="accuracy", label="Accuracy", subset=subset, value=accuracy, num=len(verdicts),
                         display_multiplier=100.0, display_unit="%", precision=1, direction="higher_is_better", primary=False))
        for i, ok in enumerate(verdicts):
            db.add(SampleResult(run_id=run_id, idx=i, subset=subset, question=f"q{i}", target="B", prediction=f"p{run_id}-{i}",
                                is_correct=ok, score=None if ok is None else float(ok), latency=1.0 + i))
        db.commit()


@pytest.fixture
def three(client, model, vmcq_dataset):
    m2 = client.post("/api/v1/models", json={**MODEL, "name": "m2"}).json()
    m3 = client.post("/api/v1/models", json={**MODEL, "name": "m3"}).json()
    runs = [make_run(client, m, vmcq_dataset) for m in (model, m2, m3)]
    complete(runs[0]["id"], 0.75, [True, True, False, True])
    complete(runs[1]["id"], 0.5, [True, False, False, True])
    complete(runs[2]["id"], 0.25, [False, False, False, True])
    return runs


def ids(runs):
    return ",".join(str(r["id"]) for r in runs)


def test_compare_returns_runs_and_metrics(client, three):
    r = client.get("/api/v1/compare", params={"run_ids": ids(three)}).json()
    assert [x["model_name"] for x in r["runs"]] == ["m1", "m2", "m3"]
    assert r["runs"][0]["headline"]["display"] == "75.0%"
    assert {m["subset"] for m in r["metrics"][str(three[0]["id"])]} == {"OVERALL", "demo"}
    assert r["warnings"] == []  # same dataset version, same settings, all completed


def test_compare_needs_two_to_eight_runs(client, three):
    assert client.get("/api/v1/compare", params={"run_ids": str(three[0]["id"])}).json()["code"] == "too_few_runs"
    assert client.get("/api/v1/compare", params={"run_ids": ",".join(map(str, range(1, 11)))}).json()["code"] == "too_many_runs"
    assert client.get("/api/v1/compare", params={"run_ids": "1,x"}).json()["code"] == "bad_run_ids"
    assert client.get("/api/v1/compare", params={"run_ids": f"{three[0]['id']},999"}).status_code == 404


def test_warnings_when_runs_are_not_comparable(client, model, vmcq_dataset):
    a = make_run(client, model, vmcq_dataset, limit=5, temperature=0.0)
    b = make_run(client, model, vmcq_dataset, limit=10, temperature=0.7)  # different limit and temperature
    complete(a["id"], 1.0, [True], engine_version="1.14.0")
    complete(b["id"], 1.0, [True], engine_version="1.15.0")
    text = " ".join(client.get("/api/v1/compare", params={"run_ids": ids([a, b])}).json()["warnings"])
    assert "题数限制不同" in text and "温度" in text and "引擎版本不同" in text and "样本少" in text


def test_warning_for_unfinished_run(client, three, model, vmcq_dataset):
    pending = make_run(client, model, vmcq_dataset)
    w = client.get("/api/v1/compare", params={"run_ids": ids([three[0], pending])}).json()["warnings"]
    assert any("还没有完成" in x for x in w)


def test_warning_for_different_dataset_versions(client, model, vmcq_dataset):
    import json

    body = "\n".join(json.dumps({"question": "q", "options": ["a", "b"], "answer": "A"}) for _ in range(2)).encode()
    v2 = client.post("/api/v1/datasets", data={"name": "colors", "kind": "vmcq"}, files={"file": ("c.jsonl", body)}).json()
    a, b = make_run(client, model, vmcq_dataset), make_run(client, model, v2)
    complete(a["id"], 1.0, [True]); complete(b["id"], 1.0, [True])
    assert any("不同版本" in x for x in client.get("/api/v1/compare", params={"run_ids": ids([a, b])}).json()["warnings"])
    # and a per-question comparison across versions is refused
    assert client.get("/api/v1/compare/samples", params={"run_ids": ids([a, b])}).json()["code"] == "different_datasets"


def test_disagreement_view_lists_only_questions_where_models_differ(client, three):
    page = client.get("/api/v1/compare/samples", params={"run_ids": ids(three), "view": "diff"}).json()
    # q0: T,T,F differ · q1: T,F,F differ · q2: F,F,F all wrong · q3: T,T,T all right
    assert page["total"] == 2 and [r["idx"] for r in page["items"]] == [0, 1]
    row = page["items"][0]
    assert row["question"] == "q0" and row["target"] == "B"
    assert [row["results"][str(r["id"])]["is_correct"] for r in three] == [True, True, False]
    assert row["results"][str(three[2]["id"])]["prediction"] == f"p{three[2]['id']}-0"


def test_all_wrong_and_all_views(client, three):
    wrong = client.get("/api/v1/compare/samples", params={"run_ids": ids(three), "view": "all_wrong"}).json()
    assert [r["idx"] for r in wrong["items"]] == [2]
    assert client.get("/api/v1/compare/samples", params={"run_ids": ids(three), "view": "all"}).json()["total"] == 4
    assert client.get("/api/v1/compare/samples", params={"run_ids": ids(three), "view": "bogus"}).status_code == 422


def test_disagreement_ignores_samples_without_a_verdict(client, model, vmcq_dataset):
    m2 = client.post("/api/v1/models", json={**MODEL, "name": "m2"}).json()
    a, b = make_run(client, model, vmcq_dataset), make_run(client, m2, vmcq_dataset)
    complete(a["id"], 1.0, [True, None]); complete(b["id"], 1.0, [True, False])
    page = client.get("/api/v1/compare/samples", params={"run_ids": ids([a, b])}).json()
    assert page["total"] == 0  # q1 has a verdict from only one model, so there is nothing to disagree about


def test_samples_page_and_subset_filter(client, model, vmcq_dataset):
    m2 = client.post("/api/v1/models", json={**MODEL, "name": "m2"}).json()
    a, b = make_run(client, model, vmcq_dataset), make_run(client, m2, vmcq_dataset)
    complete(a["id"], 0.0, [True] * 6, subset="s1"); complete(b["id"], 0.0, [False] * 6, subset="s1")
    with SessionLocal() as db:
        for rid in (a["id"], b["id"]):
            db.add(SampleResult(run_id=rid, idx=0, subset="s2", question="other", is_correct=rid == a["id"]))
        db.commit()
    p1 = client.get("/api/v1/compare/samples", params={"run_ids": ids([a, b]), "page_size": 4}).json()
    assert p1["total"] == 7 and len(p1["items"]) == 4
    p2 = client.get("/api/v1/compare/samples", params={"run_ids": ids([a, b]), "page_size": 4, "page": 2}).json()
    assert len(p2["items"]) == 3
    only = client.get("/api/v1/compare/samples", params={"run_ids": ids([a, b]), "subset": "s2"}).json()
    assert only["total"] == 1 and only["items"][0]["question"] == "other"
