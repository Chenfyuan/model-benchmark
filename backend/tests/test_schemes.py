import json

import pytest
from sqlalchemy import update

from app.db import SessionLocal
from app.models import RunMetric
from conftest import MODEL
from test_compare import complete, make_run


@pytest.fixture
def two_datasets(client, vmcq_dataset):
    body = b"\n".join(json.dumps({"question": "q", "options": ["a", "b"], "answer": "A"}).encode() for _ in range(2))
    second = client.post("/api/v1/datasets", data={"name": "docs", "kind": "vmcq"}, files={"file": ("d.jsonl", body)}).json()
    return vmcq_dataset, second


def scheme(client, items, name="s1"):
    r = client.post("/api/v1/schemes", json={"name": name, "items": items})
    assert r.status_code == 201, r.text
    return r.json()


def finished(client, model, ds, accuracy):
    rid = make_run(client, model, ds)["id"]
    complete(rid, accuracy, [True, False])
    return rid


def composite(client, runs, scheme_id):
    r = client.get("/api/v1/compare/composite", params={"run_ids": ",".join(map(str, runs)), "scheme_id": scheme_id})
    assert r.status_code == 200, r.text
    return r.json()


def test_scheme_crud_and_validation(client, two_datasets):
    s = scheme(client, [{"dataset_name": "colors", "weight": 3}, {"dataset_name": "docs", "weight": 1}])
    assert [round(i["weight_pct"]) for i in s["items"]] == [75, 25]  # weights are relative
    assert client.get("/api/v1/schemes").json()[0]["name"] == "s1"
    upd = client.put(f"/api/v1/schemes/{s['id']}", json={"name": "文档场景", "items": [{"dataset_name": "docs", "weight": 1}]}).json()
    assert upd["name"] == "文档场景" and len(upd["items"]) == 1
    bad = lambda items, name="x": client.post("/api/v1/schemes", json={"name": name, "items": items})
    assert bad([]).status_code == 422
    assert bad([{"dataset_name": "colors", "weight": 0}]).status_code == 422
    assert bad([{"dataset_name": "colors", "weight": -1}]).status_code == 422
    assert bad([{"dataset_name": "nope", "weight": 1}]).json()["code"] == "dataset_not_found"
    assert bad([{"dataset_name": "colors", "weight": 1}] * 2).json()["code"] == "duplicate_dataset"
    scheme(client, [{"dataset_name": "docs", "weight": 1}], name="dup")
    assert bad([{"dataset_name": "docs", "weight": 1}], name="dup").status_code == 409
    assert client.delete(f"/api/v1/schemes/{s['id']}").status_code == 204
    assert client.put(f"/api/v1/schemes/{s['id']}", json={"name": "z", "items": [{"dataset_name": "docs", "weight": 1}]}).status_code == 404


def test_composite_is_the_weighted_average_and_models_are_ranked(client, model, two_datasets):
    colors, docs = two_datasets
    other = client.post("/api/v1/models", json={**MODEL, "name": "m2"}).json()
    a = [finished(client, model, colors, 0.8), finished(client, model, docs, 0.6)]
    b = [finished(client, other, colors, 0.5), finished(client, other, docs, 0.9)]
    s = scheme(client, [{"dataset_name": "colors", "weight": 70}, {"dataset_name": "docs", "weight": 30}])
    r = composite(client, a + b, s["id"])
    assert [m["model_name"] for m in r["models"]] == ["m1", "m2"]  # 0.7*80+0.3*60 = 74 beats 0.7*50+0.3*90 = 62
    assert r["models"][0]["score"] == pytest.approx(74) and r["models"][1]["score"] == pytest.approx(62)
    assert [round(p["weight_pct"]) for p in r["models"][0]["parts"]] == [70, 30]
    # other weights, same data, the other model wins
    s2 = scheme(client, [{"dataset_name": "colors", "weight": 1}, {"dataset_name": "docs", "weight": 9}], name="docs-heavy")
    r2 = composite(client, a + b, s2["id"])
    assert [m["model_name"] for m in r2["models"]] == ["m2", "m1"] and r2["models"][0]["score"] == pytest.approx(86)


def test_no_composite_when_a_dataset_is_missing_or_the_metric_is_not_a_percentage(client, model, two_datasets):
    colors, docs = two_datasets
    other = client.post("/api/v1/models", json={**MODEL, "name": "m2"}).json()
    a = [finished(client, model, colors, 0.8), finished(client, model, docs, 0.6)]
    b = [finished(client, other, colors, 0.5)]  # m2 was never evaluated on docs
    s = scheme(client, [{"dataset_name": "colors", "weight": 1}, {"dataset_name": "docs", "weight": 1}])
    r = composite(client, a + b, s["id"])
    m2 = next(m for m in r["models"] if m["model_name"] == "m2")
    assert m2["score"] is None and m2["missing"] == ["docs"]
    assert r["models"][-1]["model_name"] == "m2"  # incomplete ones go last
    with SessionLocal() as db:  # make m1's docs metric a non-percentage one
        db.execute(update(RunMetric).where(RunMetric.run_id == a[1], RunMetric.primary.is_(True)).values(display_unit="", display_multiplier=1.0))
        db.commit()
    m1 = next(m for m in composite(client, a + b, s["id"])["models"] if m["model_name"] == "m1")
    assert m1["score"] is None and "不是百分比" in m1["problems"][0]


def test_composite_uses_reviewed_scores_newest_run_and_flags_trials(client, model, two_datasets):
    colors, docs = two_datasets
    old = finished(client, model, colors, 0.0)
    new = finished(client, model, colors, 0.5)  # a later run of the same model and dataset replaces the older one
    d = finished(client, model, docs, 1.0)
    with SessionLocal() as db:
        from app.models import Run, SampleResult

        db.execute(update(Run).where(Run.id == new).values(limit=2))
        s0 = db.query(SampleResult).filter_by(run_id=new, idx=1).one()  # the wrong answer turns out right
        s0.review_correct = True
        s0.final_correct = True
        db.commit()
    s = scheme(client, [{"dataset_name": "colors", "weight": 1}, {"dataset_name": "docs", "weight": 1}])
    r = composite(client, [old, new, d], s["id"])["models"][0]
    colors_part = next(p for p in r["parts"] if p["dataset_name"] == "colors")
    assert colors_part["run_id"] == new and colors_part["reviewed"] is True and colors_part["value"] == pytest.approx(100)
    assert r["score"] == pytest.approx(100) and r["trial"] is True


def test_composite_unknown_scheme(client, model, two_datasets):
    colors, _ = two_datasets
    a, b = finished(client, model, colors, 0.5), finished(client, model, colors, 0.5)
    assert client.get("/api/v1/compare/composite", params={"run_ids": f"{a},{b}", "scheme_id": 99}).status_code == 404


def test_compare_report_can_include_the_composite(client, model, two_datasets):
    colors, docs = two_datasets
    runs = [finished(client, model, colors, 0.8), finished(client, model, docs, 0.6)]
    s = scheme(client, [{"dataset_name": "colors", "weight": 3}, {"dataset_name": "docs", "weight": 1}], name="场景 <A>")
    html = client.get("/api/v1/compare/report", params={"run_ids": ",".join(map(str, runs)), "scheme_id": s["id"]}).text
    assert "综合得分 · 场景 &lt;A&gt;" in html and "75.0" in html or "<b>75.0</b>" in html  # 0.75*80 + 0.25*60 = 75
    assert "colors 75%" in html and "场景 <A>" not in html
    plain = client.get("/api/v1/compare/report", params={"run_ids": ",".join(map(str, runs))}).text
    assert "综合得分" not in plain
    assert client.get("/api/v1/compare/report", params={"run_ids": ",".join(map(str, runs)), "scheme_id": 99}).status_code == 404
