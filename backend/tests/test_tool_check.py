import json

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Dataset, SampleResult
from app.services.dataset_validation import DatasetError, ingest_upload, validate_row
from app.services.tool_check import apply_tool_check, check_calls, values_equal
from app.worker import save_results
from conftest import MODEL
from test_compare import make_run
from test_rescoring import _parsed

TOOL = {"type": "function", "function": {"name": "get_weather", "parameters": {"type": "object", "properties": {"city": {"type": "string"}}}}}
CALL = lambda **a: {"name": "get_weather", "arguments": a}
EXP = [{"name": "get_weather", "arguments": {"city": "Paris"}}]


# ------------------------------------------------------------------ the comparison

@pytest.mark.parametrize("exp,act,ok", [
    ("Paris", "paris ", True), ("Paris", "London", False), (5, "5", True), (5, 5.0, True), ("1,000", 1000, True), (5, "6", False),
    (True, "true", True), ({"a": 1}, {"a": "1", "extra": 2}, True), ({"a": 1}, {"b": 1}, False), ([1, 2], ["1", 2], True), ([1, 2], [2, 1], False),
    ({"$any": True}, "whatever", True), ({"$regex": "^Par"}, "Paris", True), ({"$regex": "^Par"}, "Lyon", False),
])
def test_value_comparison(exp, act, ok):
    assert values_equal(exp, act) is ok


def test_missing_argument_never_matches_any_or_regex():
    from app.services.tool_check import MISSING

    assert not values_equal({"$any": True}, MISSING) and not values_equal("x", MISSING)


def test_calls_are_matched_by_name_and_arguments():
    assert check_calls(EXP, [CALL(city="Paris")]) is None
    assert check_calls(EXP, [{"name": "get_weather", "arguments": json.dumps({"city": "PARIS", "unit": "c"})}]) is None  # JSON string, extra arg
    assert "期望 \"Paris\"，实际 \"Tokyo\"" in check_calls(EXP, [CALL(city="Tokyo")])
    assert "city 缺失" in check_calls(EXP, [CALL(unit="c")])
    assert "没有调用工具" == check_calls(EXP, [])
    assert "没有调用 get_weather" in check_calls(EXP, [{"name": "search", "arguments": {}}])
    assert "不是合法的 JSON" in check_calls(EXP, [{"name": "get_weather", "arguments": "{not json"}])


def test_several_expected_calls_any_order_and_extra_calls():
    two = [{"name": "get_weather", "arguments": {"city": "Paris"}}, {"name": "get_weather", "arguments": {"city": "Rome"}}]
    assert check_calls(two, [CALL(city="Rome"), CALL(city="Paris")]) is None
    assert check_calls(two, [CALL(city="Paris")]) is not None  # one expected call is missing
    assert check_calls(two, [CALL(city="Paris"), CALL(city="Paris")]) is not None  # a call cannot be used twice
    assert "多调用了" in check_calls(EXP, [CALL(city="Paris"), CALL(city="Rome")])
    assert check_calls(EXP, [CALL(city="Paris"), CALL(city="Rome")], allow_extra=True) is None


# ------------------------------------------------------------------ dataset rows

def row(**extra):
    return {"messages": [{"role": "user", "content": "weather in Paris?"}], "tools": [TOOL], "should_call_tool": True, **extra}


def test_row_validation_of_expected_calls():
    assert validate_row("fc", row(expected_calls=EXP)) == []
    assert any("非空列表" in e for e in validate_row("fc", row(expected_calls=[])))
    assert any("不在 tools 里" in e for e in validate_row("fc", row(expected_calls=[{"name": "nope", "arguments": {}}])))
    assert any("should_call_tool 为 true" in e for e in validate_row("fc", row(should_call_tool=False, expected_calls=EXP)))
    assert any("正则" in e for e in validate_row("fc", row(expected_calls=[{"name": "get_weather", "arguments": {"city": {"$regex": "("}}}])))
    assert any("allow_extra_calls" in e for e in validate_row("fc", row(expected_calls=EXP, allow_extra_calls="yes")))


# ------------------------------------------------------------------ in a run

@pytest.fixture
def fc_run(client, model, tmp_path):
    rows = [row(expected_calls=EXP), row(expected_calls=[{"name": "get_weather", "arguments": {"city": "Tokyo"}}]), row(),
            {"messages": [{"role": "user", "content": "hello"}], "tools": [TOOL], "should_call_tool": False}]
    rows[0]["messages"][0]["content"] = "weather in Paris?"
    rows[1]["messages"][0]["content"] = "weather in Tokyo?"
    rows[2]["messages"][0]["content"] = "weather in Cairo?"
    body = "\n".join(map(json.dumps, rows)).encode()
    ds = client.post("/api/v1/datasets", data={"name": "fc-args", "kind": "fc"}, files={"file": ("t.jsonl", body)}).json()
    assert ds["num_samples"] == 4
    rid = client.post("/api/v1/runs", json={"model_ids": [model["id"]], "dataset_ids": [ds["id"]]}).json()[0]["id"]
    return rid


def collect(rid, calls):
    """Engine said 'passed' for every sample (it only checks 'called / well formed')."""
    parsed = _parsed([(None, None)] * 4)
    qs = ["weather in Paris?", "weather in Tokyo?", "weather in Cairo?", "hello"]
    for i, s in enumerate(parsed.samples):
        s.update(question=qs[i], is_correct=True, score=1.0, target=None, prediction=None, tool_calls=calls[i])
    save_results(rid, parsed)


def test_wrong_argument_value_downgrades_an_engine_pass(client, fc_run):
    collect(fc_run, [[CALL(city="Paris")], [CALL(city="Kyoto")], [CALL(city="Cairo")], None])
    got = {s["idx"]: s for s in client.get(f"/api/v1/runs/{fc_run}/samples").json()["items"]}
    assert got[0]["final_correct"] is True and got[0]["auto_correct"] is None  # right value: nothing to say
    assert got[1]["is_correct"] is True and got[1]["final_correct"] is False and got[1]["auto_correct"] is False  # engine said pass, value is wrong
    assert "期望 \"Tokyo\"，实际 \"Kyoto\"" in got[1]["auto_reason"]
    assert got[0]["target"] == 'get_weather({"city": "Paris"})'  # the expectation is shown as the standard answer
    assert got[2]["final_correct"] is True and got[2]["target"] is None  # no expectation for this row: only the engine's verdict
    assert got[3]["final_correct"] is True


def test_adjusted_score_and_filters_count_the_downgrades(client, fc_run):
    from app.db import SessionLocal
    from app.models import RunMetric, Run
    from sqlalchemy import update

    collect(fc_run, [[CALL(city="Paris")], [CALL(city="Kyoto")], [CALL(city="Cairo")], None])
    with SessionLocal() as db:
        db.execute(update(Run).where(Run.id == fc_run).values(status="completed"))
        db.add(RunMetric(run_id=fc_run, kind="quality", key="pass", label="Pass", subset="OVERALL", value=1.0, num=4,
                         display_multiplier=100.0, display_unit="%", precision=1, direction="higher_is_better", primary=True))
        db.commit()
    r = client.get(f"/api/v1/runs/{fc_run}").json()
    assert r["headline"]["display"] == "100.0%" and r["adjusted"]["display"] == "75.0%"
    assert r["adjusted"]["n_args"] == 1 and r["adjusted"]["n_lenient"] == 0
    assert client.get(f"/api/v1/runs/{fc_run}/samples", params={"correct": "false"}).json()["total"] == 1
    assert client.get(f"/api/v1/runs/{fc_run}/samples", params={"correct": "changed"}).json()["total"] == 1


def test_a_person_can_overrule_the_argument_check(client, fc_run):
    collect(fc_run, [[CALL(city="Paris")], [CALL(city="Kyoto")], [CALL(city="Cairo")], None])
    s = [x for x in client.get(f"/api/v1/runs/{fc_run}/samples").json()["items"] if x["idx"] == 1][0]
    out = client.put(f"/api/v1/runs/{fc_run}/samples/{s['id']}/review", json={"correct": True, "note": "Kyoto 也可以"}).json()
    assert out["final_correct"] is True
    collect(fc_run, [[CALL(city="Paris")], [CALL(city="Kyoto")], [CALL(city="Cairo")], None])  # a retry re-collects: the decision is kept
    again = [x for x in client.get(f"/api/v1/runs/{fc_run}/samples").json()["items"] if x["idx"] == 1][0]
    assert again["review_correct"] is True and again["final_correct"] is True


def test_rescore_applies_the_check_to_an_existing_run(client, fc_run):
    from app.models import Run
    from sqlalchemy import update

    collect(fc_run, [[CALL(city="Paris")], [CALL(city="Kyoto")], [CALL(city="Cairo")], None])
    with SessionLocal() as db:
        for s in db.scalars(select(SampleResult)):
            s.auto_correct = s.auto_reason = s.final_correct = None  # as a run collected before this feature existed
        db.execute(update(Run).where(Run.id == fc_run).values(status="completed"))
        db.commit()
    out = client.post(f"/api/v1/runs/{fc_run}/rescore").json()
    assert out["downgraded"] == 1 and out["upgraded"] == 0
    assert [x["final_correct"] for x in client.get(f"/api/v1/runs/{fc_run}/samples").json()["items"]] == [True, False, True, True]


def test_upload_accepts_and_rejects_expectations(client, tmp_path):
    ok = ingest_upload("fc", "t.jsonl", json.dumps(row(expected_calls=EXP)).encode(), tmp_path / "ok", 5)
    assert ok == 1
    with pytest.raises(DatasetError, match="不在 tools 里"):
        ingest_upload("fc", "t.jsonl", json.dumps(row(expected_calls=[{"name": "x", "arguments": {}}])).encode(), tmp_path / "bad", 5)
