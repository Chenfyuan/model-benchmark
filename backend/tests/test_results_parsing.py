"""Parsers run against real EvalScope 1.14.0 output recorded in tests/fixtures (sanitised)."""
import base64
import json

import pytest

from app.engines.base import Endpoint, RunContext
from app.engines.evalscope_adapter import EvalScopeAdapter
from app.engines.evalscope_results import main_score, parse_report, parse_review_row
from conftest import FIXTURES


def _report(name):
    return json.loads((FIXTURES / name / "reports" / f"{name}.json").read_text())


def _rows(name):
    return [json.loads(line) for line in (FIXTURES / name / "reviews" / f"{name}_demo.jsonl").read_text().splitlines()]


def test_report_metrics_and_perf():
    rows = parse_report(_report("general_vmcq"))
    overall = [r for r in rows if r["subset"] == "OVERALL" and r["kind"] == "quality"]
    assert len(overall) == 1
    acc = overall[0]
    assert acc["key"] == "accuracy" and acc["label"] == "Accuracy" and acc["primary"]
    assert acc["value"] == 1.0 and acc["display_multiplier"] == 100.0 and acc["display_unit"] == "%"
    perf = {r["key"]: r for r in rows if r["kind"] == "perf"}
    assert perf["latency_mean"]["value"] > 0 and perf["latency_mean"]["direction"] == "lower_is_better"
    assert perf["input_tokens_mean"]["value"] > 1000  # the gateway overhead seen in the real run
    assert perf["total_input_tokens"]["value"] > 0


def test_report_function_calling_has_several_metrics_and_one_primary():
    rows = parse_report(_report("general_fc"))
    quality_overall = [r for r in rows if r["subset"] == "OVERALL" and r["kind"] == "quality"]
    assert {r["key"] for r in quality_overall} >= {"tool_call_f1"}
    assert sum(r["primary"] for r in rows) == 1


def test_report_subsets_are_listed():
    rows = parse_report(_report("general_vmcq"))
    assert {r["subset"] for r in rows if r["key"] == "accuracy"} == {"OVERALL", "demo"}


def test_review_row_with_local_image_is_copied(tmp_path):
    src = tmp_path / "pic.png"
    src.write_bytes(b"\x89PNG-fake")
    row = _rows("general_vmcq")[0]
    for part in row["messages"][0]["content"]:
        if part["type"] == "image":
            part["image"] = str(src)
    s = parse_review_row(row, "demo", tmp_path / "media")
    assert s["media"][0]["kind"] == "file"
    assert (tmp_path / s["media"][0]["ref"].replace("media/", "media/")).parent == tmp_path / "media"
    assert (tmp_path / s["media"][0]["ref"]).read_bytes() == b"\x89PNG-fake"
    assert s["target"] in ("A", "B", "C", "D") and s["extracted"] == s["target"]
    assert s["is_correct"] is True and s["score"] == 1.0
    assert s["latency"] > 0 and s["input_tokens"] > 1000 and s["output_tokens"] > 0
    assert "Answer the following multiple choice question" in s["question"]


def test_review_row_with_missing_image_is_marked(tmp_path):
    s = parse_review_row(_rows("general_vmcq")[0], "demo", tmp_path / "media")  # fixture paths point nowhere
    assert s["media"][0]["kind"] == "missing"


def test_review_row_with_data_url_image(tmp_path):
    row = _rows("general_vmcq")[0]
    for part in row["messages"][0]["content"]:
        if part["type"] == "image":
            part["image"] = "data:image/png;base64," + base64.b64encode(b"\x89PNG-data").decode()
    s = parse_review_row(row, "demo", tmp_path / "media")
    assert s["media"][0]["ref"].endswith(".png")
    assert (tmp_path / s["media"][0]["ref"]).read_bytes() == b"\x89PNG-data"


def test_review_row_function_calling():
    rows = _rows("general_fc")
    called = [parse_review_row(r, "demo", None) for r in rows]  # no media here, so no directory is needed
    first = called[0]
    assert first["tool_calls"] == [{"name": "get_weather", "arguments": {"city": "Paris"}}]
    assert first["is_correct"] is True and first["scores"]["passed"] is True
    assert first["question"] == "What's the weather in Paris?"
    assert first["prediction"] is None and first["extracted"] is None  # the structured call is the answer, not echoed text
    text_row = rows[0]  # same row, but the model answered in plain text instead of calling the tool
    text_row["messages"][1].update(content="Bonjour.", tool_calls=None)
    text = parse_review_row(text_row, "demo", None)
    assert text["tool_calls"] is None and text["prediction"] == "Bonjour."


def test_review_row_vqa_with_judge(tmp_path):
    s = parse_review_row(_rows("general_vqa")[0], "demo", tmp_path / "media")
    assert s["extracted"] == s["target"] and s["is_correct"] is True
    assert s["judge_output"]  # the judge model's raw verdict is kept


@pytest.mark.parametrize("score,expected", [
    ({"value": {"passed": False, "x": 1}}, 0.0),
    ({"value": {"acc": 0.5}, "main_score_name": "acc"}, 0.5),
    ({"value": {"relaxed_acc": 1.0}}, 1.0),
    ({"value": {}}, None),
    ({"value": 0.75}, 0.75),
])
def test_main_score(score, expected):
    assert main_score(score) == expected


# ---------------------------------------------------------------- adapter

def _ctx(tmp_path, protocol="openai", kind="vqa"):
    return RunContext(
        run_id=1, work_dir=tmp_path, model=Endpoint(protocol, "http://gw.example.com/", "claude-x", "sk-very-secret"),
        dataset_kind=kind, benchmark_id="chartqa" if kind == "benchmark" else None, dataset_path="/data/ds1",
        judge=Endpoint("openai", "http://judge.example.com", "judge-m", "sk-judge-secret"), limit=20,
    )


def test_prepare_keeps_secrets_out_of_files(tmp_path):
    p = EvalScopeAdapter().prepare(_ctx(tmp_path))
    cfg_text = (tmp_path / "task.json").read_text()
    assert "sk-very-secret" not in cfg_text and "sk-judge-secret" not in cfg_text
    assert p.env["EVAL_API_KEY"] == "sk-very-secret" and p.env["JUDGE_API_KEY"] == "sk-judge-secret"
    cfg = json.loads(cfg_text)
    assert cfg["eval_type"] == "openai_api" and cfg["api_url"] == "http://gw.example.com/v1"
    assert cfg["datasets"] == ["general_vqa"] and cfg["dataset_args"]["general_vqa"] == {"local_path": "/data/ds1", "subset_list": ["data"]}
    assert cfg["limit"] == 20 and cfg["judge"]["api_url"] == "http://judge.example.com/v1"


def test_prepare_anthropic_and_builtin(tmp_path):
    p = EvalScopeAdapter().prepare(_ctx(tmp_path, protocol="anthropic", kind="benchmark"))
    cfg = json.loads((tmp_path / "task.json").read_text())
    assert cfg["eval_type"] == "anthropic_api" and cfg["api_url"] == "http://gw.example.com"  # no /v1 for the Anthropic SDK
    assert cfg["datasets"] == ["chartqa"] and cfg["dataset_args"] == {}
    assert p.cmd[1:3] == ["-m", "app.engines.evalscope_task"]


@pytest.mark.parametrize("tail,stage,progress", [
    ("", "preparing", None),
    ("Downloading data:  10%|#| 7.3M/72.6M", "downloading", None),
    ("Downloading data: 100%\rEvaluating[chartqa]:  50%|#####     | 3/6 [00:02<00:02]", "evaluating", 0.5),
    ("Evaluating[chartqa]: 100%|##########| 6/6 [00:06<00:00]\rDownloading data: 5%", "downloading", None),
])
def test_progress_from_log(tail, stage, progress):
    assert EvalScopeAdapter().progress(tail) == (stage, progress)
