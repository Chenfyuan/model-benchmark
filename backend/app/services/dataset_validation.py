"""Validation and storage of uploaded custom datasets.

Standard internal formats are EvalScope's custom formats (design doc, section 4.2):
  vqa   - JSONL: {"messages": [...OpenAI messages...], "answer": "..."}  (media inside messages, or placeholder columns)
  vmcq  - JSONL: {"question": "...<image 1>...", "options": [...], "answer": "B", "image_1": "<path|url|data-url>"}
  fc    - JSONL: {"messages": [...], "tools": [...OpenAI tools...], "should_call_tool": true,
                  "expected_calls": [{"name": "...", "arguments": {...}}]  (optional: also check the argument values)}
Uploads are a single .jsonl, or a .zip holding one .jsonl plus the media files it references by relative path.
"""
from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

KINDS = ("vqa", "vmcq", "fc")
MEDIA_COLUMN = re.compile(r"^(image|video|audio)_\d+$")
MAX_ERRORS = 20


class DatasetError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors[:3]))
        self.errors = errors


def _is_remote(v: str) -> bool:
    return v.startswith(("http://", "https://", "data:"))


def _resolve(value: Any, base: Path) -> Any:
    """Rewrite a relative media path to an absolute one if the file exists under `base`."""
    if not isinstance(value, str) or _is_remote(value) or Path(value).is_absolute():
        return value
    cand = (base / value).resolve()
    if base.resolve() in cand.parents and cand.is_file():
        return str(cand)
    return value


def resolve_media_paths(row: dict, base: Path) -> dict:
    for msg in row.get("messages") or []:
        content = msg.get("content")
        if isinstance(content, list):
            for part in content:
                for key in ("image_url", "video_url"):
                    if isinstance(part.get(key), dict) and "url" in part[key]:
                        part[key]["url"] = _resolve(part[key]["url"], base)
    for k, v in list(row.items()):
        if MEDIA_COLUMN.match(k):
            row[k] = _resolve(v, base)
        elif k in ("images", "videos", "audios") and isinstance(v, list):
            row[k] = [_resolve(x, base) for x in v]
    return row


def _media_refs(row: dict) -> list[str]:
    refs: list[str] = []
    for msg in row.get("messages") or []:
        content = msg.get("content")
        if isinstance(content, list):
            for part in content:
                for key in ("image_url", "video_url"):
                    if isinstance(part.get(key), dict) and isinstance(part[key].get("url"), str):
                        refs.append(part[key]["url"])
    for k, v in row.items():
        if MEDIA_COLUMN.match(k) and isinstance(v, str):
            refs.append(v)
        elif k in ("images", "videos", "audios") and isinstance(v, list):
            refs.extend(x for x in v if isinstance(x, str))
    return refs


def validate_row(kind: str, row: Any) -> list[str]:
    if not isinstance(row, dict):
        return ["每行必须是 JSON 对象"]
    errs: list[str] = []
    if kind in ("vqa", "fc"):
        msgs = row.get("messages")
        if not isinstance(msgs, list) or not msgs:
            errs.append("缺少 messages（OpenAI 消息列表）")
        elif not all(isinstance(m, dict) and "role" in m and "content" in m for m in msgs):
            errs.append("messages 里每条消息都需要 role 和 content")
    if kind == "vqa" and "answer" not in row:
        errs.append("缺少 answer（标准答案）；没有标准答案的数据集无法打分")
    if kind == "vmcq":
        opts = row.get("options")
        if not isinstance(row.get("question"), str) or not row["question"].strip():
            errs.append("缺少 question")
        if not isinstance(opts, list) or len(opts) < 2:
            errs.append("options 必须是至少两项的列表")
        ans = row.get("answer")
        if not isinstance(ans, str) or len(ans) != 1 or not ans.isalpha():
            errs.append("answer 必须是单个选项字母")
        elif isinstance(opts, list) and ord(ans.upper()) - 65 >= len(opts):
            errs.append(f"answer {ans} 超出选项范围（共 {len(opts)} 项）")
    if kind == "fc":
        tools = row.get("tools")
        if not isinstance(tools, list) or not tools:
            errs.append("缺少 tools（OpenAI 格式的工具定义）")
        elif not all(isinstance(t, dict) and isinstance(t.get("function"), dict) and t["function"].get("name") for t in tools):
            errs.append("tools 里每项都需要 function.name")
        if not isinstance(row.get("should_call_tool"), bool):
            errs.append("should_call_tool 必须是 true 或 false")
        from .tool_check import validate_expected

        errs.extend(validate_expected(row))
    return errs


def _safe_extract(zf: zipfile.ZipFile, dest: Path, max_bytes: int) -> None:
    total = 0
    for info in zf.infolist():
        total += info.file_size
        if total > max_bytes:
            raise DatasetError(["压缩包解压后超过大小上限"])
        target = (dest / info.filename).resolve()
        if dest.resolve() not in target.parents and target != dest.resolve():
            raise DatasetError([f"压缩包里有越界路径：{info.filename}"])
    zf.extractall(dest)


def ingest_upload(kind: str, filename: str, raw: bytes, dest: Path, max_mb: int) -> int:
    """Validate an upload and write it to `dest/data.jsonl` (media copied alongside). Returns the number of samples.

    On any error `dest` is removed and DatasetError is raised.
    """
    if kind not in KINDS:
        raise DatasetError([f"kind 必须是 {', '.join(KINDS)} 之一"])
    if len(raw) > max_mb * 1024 * 1024:
        raise DatasetError([f"文件超过 {max_mb} MB 上限"])
    dest.mkdir(parents=True, exist_ok=True)
    try:
        if filename.lower().endswith(".zip"):
            import io

            media_dir = dest / "media"
            media_dir.mkdir(exist_ok=True)
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                _safe_extract(zf, media_dir, max_mb * 1024 * 1024 * 4)
            jsonls = sorted(media_dir.rglob("*.jsonl"))
            if len(jsonls) != 1:
                raise DatasetError([f"压缩包里需要恰好一个 .jsonl 文件，实际有 {len(jsonls)} 个"])
            text, base = jsonls[0].read_text(encoding="utf-8"), jsonls[0].parent
        elif filename.lower().endswith(".jsonl"):
            text, base = raw.decode("utf-8"), dest
        elif filename.lower().endswith((".tsv", ".csv")):
            from .tsv_import import convert

            if kind == "fc":
                raise DatasetError(["工具调用数据集不支持表格格式，请用 .jsonl"])
            converted, got = convert(raw.decode("utf-8-sig"))
            if got != kind:
                raise DatasetError([f"表格内容是{'选择题（有 A/B/C… 选项列）' if got == 'vmcq' else '开放问答（没有选项列）'}，请把类型改成 {got}"])
            text, base = "\n".join(json.dumps(r, ensure_ascii=False) for r in converted), dest
        else:
            raise DatasetError(["只支持 .jsonl、.zip，或 VLMEvalKit 的 .tsv / .csv 文件"])

        rows: list[dict] = []
        errors: list[str] = []
        for lineno, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                errors.append(f"第 {lineno} 行不是合法 JSON：{e.msg}")
                continue
            errs = validate_row(kind, row)
            if not errs:
                row = resolve_media_paths(row, base)
                for ref in _media_refs(row):
                    if not _is_remote(ref) and not Path(ref).is_file():
                        errs.append(f"找不到媒体文件：{ref[:80]}")
            errors.extend(f"第 {lineno} 行：{e}" for e in errs)
            rows.append(row)
            if len(errors) >= MAX_ERRORS:
                break
        if not rows:
            errors.append("文件里没有任何样本")
        if errors:
            raise DatasetError(errors[:MAX_ERRORS])
        with open(dest / "data.jsonl", "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return len(rows)
    except DatasetError:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    except (UnicodeDecodeError, zipfile.BadZipFile) as e:
        shutil.rmtree(dest, ignore_errors=True)
        raise DatasetError([f"无法读取文件：{type(e).__name__}"]) from e


def _short(o: Any, n: int = 200) -> Any:
    if isinstance(o, str):
        return o if len(o) <= n else o[:n] + f"…({len(o)} 字符)"
    if isinstance(o, list):
        return [_short(x, n) for x in o]
    if isinstance(o, dict):
        return {k: _short(v, n) for k, v in o.items()}
    return o


def preview(path: str, limit: int = 5) -> list[Any]:
    out = []
    with open(Path(path) / "data.jsonl", encoding="utf-8") as f:
        for line in f:
            out.append(_short(json.loads(line)))
            if len(out) >= limit:
                break
    return out
