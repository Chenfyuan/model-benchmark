import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import RunMetric, SampleResult
from app.services.rescoring import lenient_match
from test_compare import complete, ids, make_run


@pytest.mark.parametrize("target,pred,ok", [
    ("6.8", "6.8%", True), ("1000", "1,000", True), ("$12.50", "12.5", True), ("Paris", "paris.", True), ("ORBIT-208", " orbit-208 ", True),
    ("５", "5", True), ("6.8", "6.9", False), ("cat", "a cat sat", False), ("12", "120", False), ("A", "B", False), ("", "x", False),
])
def test_lenient_match_rules(target, pred, ok):
    assert bool(lenient_match(target, pred, None)) is ok


def test_any_of_several_targets_and_extracted_answer():
    assert lenient_match("yes, y", "I think so", "Y")
    assert not lenient_match("no", "I think so", "Y")
    assert not lenient_match("x", "z" * 500, None)  # long free text is never matched leniently


def _run(client, model, dataset, rows, accuracy, subset="demo"):
    run = make_run(client, model, dataset)
    complete(run["id"], accuracy, [r[0] for r in rows], subset=subset)
    with SessionLocal() as db:
        for s, (_, target, pred) in zip(db.scalars(select(SampleResult).where(SampleResult.run_id == run["id"]).order_by(SampleResult.idx)), rows):
            s.target, s.prediction = target, pred
        db.commit()
    return run["id"]


def test_rescore_upgrades_only_engine_wrong_answers_and_keeps_engine_score(client, model, vmcq_dataset):
    rid = _run(client, model, vmcq_dataset, [(False, "6.8", "6.8%"), (False, "cat", "dog"), (True, "7", "7"), (False, "x", "X")], 0.25)
    r = client.post(f"/api/v1/runs/{rid}/rescore").json()
    assert r["upgraded"] == 2
    got = client.get(f"/api/v1/runs/{rid}/samples", params={"page_size": 10}).json()["items"]
    assert [s["is_correct"] for s in got] == [False, False, True, False]  # the engine's verdicts untouched
    assert [s["final_correct"] for s in got] == [True, False, True, True]
    assert "数值相同" in got[0]["auto_reason"]
    run = client.get(f"/api/v1/runs/{rid}").json()
    assert run["headline"]["value"] == 0.25 and run["adjusted"]["adjusted"] == 0.75 and run["adjusted"]["n_lenient"] == 2


def test_manual_review_wins_and_can_be_cleared(client, model, vmcq_dataset):
    rid = _run(client, model, vmcq_dataset, [(False, "6.8", "6.8%"), (False, "cat", "dog")], 0.0)
    client.post(f"/api/v1/runs/{rid}/rescore")
    s = client.get(f"/api/v1/runs/{rid}/samples").json()["items"]
    # a person rejects the lenient upgrade and accepts the other answer
    a = client.put(f"/api/v1/runs/{rid}/samples/{s[0]['id']}/review", json={"correct": False, "note": "单位不对"}).json()
    b = client.put(f"/api/v1/runs/{rid}/samples/{s[1]['id']}/review", json={"correct": True}).json()
    assert a["final_correct"] is False and a["review_note"] == "单位不对" and b["final_correct"] is True
    assert client.get(f"/api/v1/runs/{rid}").json()["adjusted"]["adjusted"] == 0.5
    assert len(client.get(f"/api/v1/runs/{rid}/samples", params={"correct": "true"}).json()["items"]) == 1
    assert client.get(f"/api/v1/runs/{rid}/samples", params={"correct": "changed"}).json()["total"] == 2
    cleared = client.put(f"/api/v1/runs/{rid}/samples/{s[0]['id']}/review", json={"correct": None}).json()
    assert cleared["review_correct"] is None and cleared["final_correct"] is True  # back to the lenient verdict
    assert client.put(f"/api/v1/runs/{rid}/samples/999999/review", json={"correct": True}).status_code == 404


def test_adjusted_is_withheld_when_headline_is_not_a_mean_of_sample_scores(client, model, vmcq_dataset):
    rid = _run(client, model, vmcq_dataset, [(False, "a", "A"), (True, "b", "b")], 0.9)  # engine says 0.9 but samples average 0.5
    client.post(f"/api/v1/runs/{rid}/rescore")
    assert client.get(f"/api/v1/runs/{rid}").json()["adjusted"] is None
    assert client.get(f"/api/v1/runs/{rid}/adjusted").json() is None


def test_adjusted_follows_the_engines_aggregation_over_subsets(client, model, vmcq_dataset):
    # OVERALL is the mean of subset means (macro), subsets differ in size
    run = make_run(client, model, vmcq_dataset)
    complete(run["id"], 0.5, [False, True], subset="s1")
    with SessionLocal() as db:
        db.add_all([SampleResult(run_id=run["id"], idx=i, subset="s2", question="q", target="1", prediction=p, is_correct=c, score=float(c)) for i, (p, c) in enumerate([("1%", False), ("2", False), ("3", False), ("4", False)])])
        db.add(RunMetric(run_id=run["id"], kind="quality", key="accuracy", label="Accuracy", subset="s2", value=0.0, num=4, display_multiplier=100.0, display_unit="%", precision=1))
        head = db.scalar(select(RunMetric).where(RunMetric.run_id == run["id"], RunMetric.primary.is_(True)))
        head.value = 0.25  # macro mean of 0.5 and 0.0; the flat mean would be 1/6
        db.commit()
    client.post(f"/api/v1/runs/{run['id']}/rescore")
    adj = client.get(f"/api/v1/runs/{run['id']}/adjusted").json()
    assert adj["adjusted"] == pytest.approx(0.5 * (0.5 + 0.25))
    assert adj["subsets"]["s2"]["adjusted"] == 0.25


def test_compare_uses_final_verdicts(client, model, vmcq_dataset):
    a = _run(client, model, vmcq_dataset, [(False, "6.8", "6.8%"), (False, "x", "y")], 0.0)
    b = _run(client, model, vmcq_dataset, [(False, "6.8", "7"), (False, "x", "y")], 0.0)
    assert client.get("/api/v1/compare/samples", params={"run_ids": ids([{"id": a}, {"id": b}])}).json()["total"] == 0
    client.post(f"/api/v1/runs/{a}/rescore")
    page = client.get("/api/v1/compare/samples", params={"run_ids": ids([{"id": a}, {"id": b}])}).json()
    assert page["total"] == 1
    cell = page["items"][0]["results"][str(a)]
    assert cell["is_correct"] is True and cell["engine_correct"] is False and "数值" in cell["auto_reason"]
    assert str(a) in client.get("/api/v1/compare", params={"run_ids": ids([{"id": a}, {"id": b}])}).json()["adjusted"]


def test_rescore_requires_completed_run_and_skips_judged_runs(client, model, vmcq_dataset):
    run = make_run(client, model, vmcq_dataset)
    assert client.post(f"/api/v1/runs/{run['id']}/rescore").status_code == 409


def _parsed(preds):
    from app.engines.base import ParsedResult

    samples = [dict(idx=i, subset="demo", question="q", media=[], target=t, prediction=p, extracted=None, tool_calls=None, scores={}, score=0.0,
                    is_correct=False, judge_output=None, latency=1.0, input_tokens=1, output_tokens=1, error=None) for i, (t, p) in enumerate(preds)]
    return ParsedResult(metrics=[], samples=samples, engine_version="1.14.0")


def test_collecting_applies_lenient_and_a_retry_keeps_reviews_for_unchanged_answers(client, model, vmcq_dataset):
    from app.worker import save_results

    run = make_run(client, model, vmcq_dataset)["id"]
    save_results(run, _parsed([("6.8", "6.8%"), ("cat", "dog")]))
    got = client.get(f"/api/v1/runs/{run}/samples").json()["items"]
    assert [s["final_correct"] for s in got] == [True, False]
    client.put(f"/api/v1/runs/{run}/samples/{got[1]['id']}/review", json={"correct": True, "note": "同义"})
    client.put(f"/api/v1/runs/{run}/samples/{got[0]['id']}/review", json={"correct": False})
    save_results(run, _parsed([("6.8", "something else"), ("cat", "dog")]))  # sample 0's answer changed, sample 1's did not
    again = client.get(f"/api/v1/runs/{run}/samples").json()["items"]
    assert again[0]["review_correct"] is None and again[0]["final_correct"] is False  # stale review dropped
    assert again[1]["review_correct"] is True and again[1]["review_note"] == "同义"


def test_judged_runs_get_no_lenient_matching(client, model, vmcq_dataset):
    from app.worker import save_results

    judge = client.post("/api/v1/models", json={**model, "name": "judge", "api_key": "sk-judge-0000"}).json()
    run = make_run(client, model, vmcq_dataset, judge_model_id=judge["id"])["id"]
    save_results(run, _parsed([("6.8", "6.8%")]))
    s = client.get(f"/api/v1/runs/{run}/samples").json()["items"][0]
    assert s["auto_correct"] is None and s["final_correct"] is False
