import re

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import SampleResult
from app.worker import run_dir
from test_compare import complete, ids, make_run
from test_rescoring import _run

PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6300010000050001")


def two_runs(client, model, dataset):
    a = _run(client, model, dataset, [(False, "6.8", "6.8%"), (False, "cat", "dog"), (True, "7", "7"), (False, "x", "z")], 0.25)
    b = _run(client, model, dataset, [(False, "6.8", "7"), (True, "cat", "cat"), (True, "7", "7"), (False, "x", "z")], 0.5)
    client.post(f"/api/v1/runs/{a}/rescore")
    return a, b


def test_run_report_is_one_self_contained_page_with_scores_and_wrong_answers(client, model, vmcq_dataset):
    a, _ = two_runs(client, model, vmcq_dataset)
    r = client.get(f"/api/v1/runs/{a}/report")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    html = r.text
    assert "m1 × colors" in html and "25.0%" in html  # engine headline
    assert "复核后 <b>50.0%</b>" in html and "宽松匹配 1 题" in html  # 6.8 -> "6.8%" was upgraded
    assert "<pre>cat</pre>" in html and "<pre>dog</pre>" in html  # a wrong answer is listed with target and answer
    assert "6.8%" not in html.split("答错的题")[1]  # the lenient pass is no longer "wrong"
    assert not re.search(r'(?:src|href)="https?://', html) and "<script" not in html  # nothing external, no scripts


def test_report_escapes_user_content(client, model, vmcq_dataset):
    a, _ = two_runs(client, model, vmcq_dataset)
    with SessionLocal() as db:
        s = db.scalars(select(SampleResult).where(SampleResult.run_id == a, SampleResult.idx == 3)).one()
        s.question, s.prediction, s.review_note = "<script>alert(1)</script>", "<img src=x onerror=alert(2)>", "</pre><b>x</b>"
        db.commit()
    html = client.get(f"/api/v1/runs/{a}/report").text
    assert "<script>alert" not in html and "&lt;script&gt;alert(1)" in html and "<img src=x" not in html and "&lt;img src=x" in html
    assert "<b>x</b>" not in html


def test_report_embeds_images_and_download_header(client, model, vmcq_dataset):
    a, _ = two_runs(client, model, vmcq_dataset)
    d = run_dir(a) / "media"
    d.mkdir(parents=True)
    (d / "p.png").write_bytes(PNG)
    with SessionLocal() as db:
        s = db.scalars(select(SampleResult).where(SampleResult.run_id == a, SampleResult.idx == 1)).one()
        s.media = [{"type": "image", "kind": "file", "ref": "media/p.png"}, {"type": "image", "kind": "file", "ref": "../../../etc/passwd"}]
        db.commit()
    r = client.get(f"/api/v1/runs/{a}/report", params={"download": True})
    assert "data:image/png;base64," in r.text and r.text.count("<img") == 1  # the path-traversal ref is ignored
    assert r.headers["content-disposition"].startswith("attachment")


def test_report_needs_a_finished_run(client, model, vmcq_dataset):
    run = make_run(client, model, vmcq_dataset)
    assert client.get(f"/api/v1/runs/{run['id']}/report").status_code == 409


def test_compare_report_highlights_winner_and_lists_disagreements(client, model, vmcq_dataset):
    a, b = two_runs(client, model, vmcq_dataset)
    r = client.get("/api/v1/compare/report", params={"run_ids": f"{a},{b}"})
    assert r.status_code == 200
    html = r.text
    assert "模型对比报告" in html and 'class="num win"' in html
    assert "复核后得分" in html  # run a has an upgrade
    sec = html.split("有分歧的题")[1]
    assert "cat" in sec and "dog" in sec  # the one question the models disagree on after review (idx 1)
    assert client.get("/api/v1/compare/report", params={"run_ids": f"{a}"}).status_code == 400


def test_compare_report_requires_finished_runs(client, model, vmcq_dataset):
    a, _ = two_runs(client, model, vmcq_dataset)
    c = make_run(client, model, vmcq_dataset)["id"]
    assert client.get("/api/v1/compare/report", params={"run_ids": f"{a},{c}"}).status_code == 409


def test_a_tie_highlights_every_tied_model_despite_float_noise(client, model, vmcq_dataset):
    # a: 3 of 10 answers are right after the lenient pass -> adjusted score 3/10 = 0.3
    a = _run(client, model, vmcq_dataset, [(False, "6.8", "6.8%")] * 3 + [(False, "x", "z")] * 7, 0.0)
    client.post(f"/api/v1/runs/{a}/rescore")
    # b: headline 0.1 + 0.2, which is 0.30000000000000004 in floating point
    b = _run(client, model, vmcq_dataset, [(True, "x", "x")] * 3 + [(False, "x", "z")] * 7, 0.1 + 0.2)
    assert 0.1 + 0.2 != 0.3
    html = client.get("/api/v1/compare/report", params={"run_ids": f"{a},{b}"}).text
    row = next(r for r in html.split("<tr>") if "复核后得分" in r)
    assert row.count('num win') == 2  # both tied cells are highlighted, not just one
