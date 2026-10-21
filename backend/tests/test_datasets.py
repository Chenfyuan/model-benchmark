import io
import json
import zipfile

import pytest

from app.services.dataset_validation import DatasetError, ingest_upload, validate_row

VQA = {"messages": [{"role": "user", "content": [{"type": "text", "text": "q"}, {"type": "image_url", "image_url": {"url": "pics/a.png"}}]}],
       "answer": "A"}


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_builtin_catalog_seeded(client):
    ds = client.get("/api/v1/datasets", params={"source": "builtin"}).json()
    ids = {d["benchmark_id"]: d for d in ds}
    assert {"chartqa", "docvqa", "mm_bench", "tool_bench"} <= ids.keys()
    assert ids["chartqa"]["verified"] and ids["docvqa"]["verified"] and ids["mm_bench"]["verified"]
    assert not ids["mmmu"]["verified"]  # in EvalScope's list, never run here


def test_upload_creates_versions(client, vmcq_dataset):
    assert vmcq_dataset["version"] == 1 and vmcq_dataset["num_samples"] == 2
    body = b"\n".join(json.dumps({"question": "q", "options": ["a", "b"], "answer": "A"}).encode() for _ in range(3))
    again = client.post("/api/v1/datasets", data={"name": "colors", "kind": "vmcq"}, files={"file": ("c.jsonl", body)}).json()
    assert again["version"] == 2 and again["num_samples"] == 3


def test_preview_truncates_long_values(client):
    row = {"question": "x" * 1000, "options": ["a", "b"], "answer": "A"}
    ds = client.post("/api/v1/datasets", data={"name": "long", "kind": "vmcq"}, files={"file": ("l.jsonl", json.dumps(row).encode())}).json()
    pv = client.get(f"/api/v1/datasets/{ds['id']}/preview").json()
    assert len(pv[0]["question"]) < 300 and "1000" in pv[0]["question"]


def test_invalid_upload_reports_line_numbers_and_leaves_nothing(client):
    bad = b'{"question": "q", "options": ["a"], "answer": "Z"}\nnot json\n'
    r = client.post("/api/v1/datasets", data={"name": "bad", "kind": "vmcq"}, files={"file": ("b.jsonl", bad)})
    assert r.status_code == 422 and r.json()["code"] == "invalid_dataset"
    details = " ".join(r.json()["details"])
    assert "第 1 行" in details and "第 2 行" in details
    assert [d for d in client.get("/api/v1/datasets", params={"source": "custom"}).json()] == []


@pytest.mark.parametrize("kind,row,fragment", [
    ("vqa", {"messages": [{"role": "user", "content": "q"}]}, "answer"),
    ("vqa", {"answer": "x"}, "messages"),
    ("vmcq", {"question": "q", "options": ["a", "b"], "answer": "C"}, "超出选项范围"),
    ("fc", {"messages": [{"role": "user", "content": "q"}], "tools": [], "should_call_tool": True}, "tools"),
    ("fc", {"messages": [{"role": "user", "content": "q"}], "tools": [{"function": {"name": "f"}}], "should_call_tool": "yes"}, "should_call_tool"),
])
def test_validate_row_rejects(kind, row, fragment):
    assert any(fragment in e for e in validate_row(kind, row))


def test_zip_with_relative_media(tmp_path):
    z = _zip({"data.jsonl": (json.dumps(VQA) + "\n").encode(), "pics/a.png": b"\x89PNG fake"})
    n = ingest_upload("vqa", "set.zip", z, tmp_path / "ds", max_mb=5)
    assert n == 1
    stored = json.loads((tmp_path / "ds" / "data.jsonl").read_text())
    url = stored["messages"][0]["content"][1]["image_url"]["url"]
    assert url.startswith(str(tmp_path)) and url.endswith("pics/a.png")  # rewritten to an absolute path that exists


def test_zip_missing_media_is_rejected(tmp_path):
    z = _zip({"data.jsonl": (json.dumps(VQA) + "\n").encode()})
    with pytest.raises(DatasetError) as e:
        ingest_upload("vqa", "set.zip", z, tmp_path / "ds", max_mb=5)
    assert "找不到媒体文件" in e.value.errors[0]
    assert not (tmp_path / "ds").exists()  # cleaned up


def test_zip_slip_is_rejected(tmp_path):
    z = _zip({"../evil.txt": b"x", "data.jsonl": b"{}"})
    with pytest.raises(DatasetError) as e:
        ingest_upload("vqa", "set.zip", z, tmp_path / "ds", max_mb=5)
    assert "越界" in e.value.errors[0]
    assert not (tmp_path / "evil.txt").exists()


def test_size_limit(tmp_path):
    with pytest.raises(DatasetError):
        ingest_upload("vqa", "a.jsonl", b"x" * (2 * 1024 * 1024), tmp_path / "ds", max_mb=1)


def test_delete_dataset_in_use_conflicts(client, model, vmcq_dataset):
    client.post("/api/v1/runs", json={"model_ids": [model["id"]], "dataset_ids": [vmcq_dataset["id"]]})
    assert client.delete(f"/api/v1/datasets/{vmcq_dataset['id']}").status_code == 409
    builtin = client.get("/api/v1/datasets", params={"source": "builtin"}).json()[0]
    assert client.delete(f"/api/v1/datasets/{builtin['id']}").status_code == 409
