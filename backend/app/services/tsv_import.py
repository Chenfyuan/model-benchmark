"""Convert a VLMEvalKit-style TSV (or a CSV with the same columns) into the platform's JSONL rows.

Columns understood: index, question, A/B/C/..., answer, image (base64, a JSON list of base64 strings, or the `index`
of another row that holds the image - MMBench-style de-duplication), hint (prepended to the question), category / l2-category / split (kept as extra fields).
Rows with option columns become `vmcq`; rows without become `vqa`.
"""
from __future__ import annotations

import base64
import csv
import io
import json
import re
import sys
from typing import Any

from .dataset_validation import DatasetError

OPTION_COLUMN = re.compile(r"^[A-Z]$")
IMAGE_MAGIC = ((b"\x89PNG", "image/png"), (b"\xff\xd8\xff", "image/jpeg"), (b"GIF8", "image/gif"), (b"RIFF", "image/webp"))
EXTRA_COLUMNS = ("category", "l2-category", "split", "index")


def _empty(v: Any) -> bool:
    return v is None or str(v).strip() == "" or str(v).strip().lower() == "nan"


def _data_url(b64: str) -> str:
    if b64.startswith("data:"):
        return b64
    try:
        head = base64.b64decode(b64[:64] + "=" * (-len(b64[:64]) % 4), validate=False)[:12]
    except Exception:
        raise DatasetError(["image 列不是合法的 base64"]) from None
    mime = next((m for magic, m in IMAGE_MAGIC if head.startswith(magic)), "image/jpeg")
    return f"data:{mime};base64,{b64}"


def _images(value: str, by_index: dict[str, str], depth: int = 0) -> list[str]:
    value = value.strip()
    if not value:
        return []
    if value.startswith("["):
        try:
            items = json.loads(value.replace("'", '"'))
        except json.JSONDecodeError:
            raise DatasetError(["image 列看起来是列表，但无法解析"]) from None
        return [u for x in items for u in _images(str(x), by_index, depth + 1)]
    if len(value) <= 64 and value in by_index and depth < 5:  # a reference to another row's image
        return _images(by_index[value], by_index, depth + 1)
    return [_data_url(value)]


def convert(text: str) -> tuple[list[dict], str]:
    """Returns (rows, kind)."""
    csv.field_size_limit(min(sys.maxsize, 2**31 - 1))
    first = text.split("\n", 1)[0]
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter="\t" if "\t" in first else ",")
    cols = reader.fieldnames or []
    if "question" not in cols or "answer" not in cols:
        raise DatasetError(["表格需要 question 和 answer 两列（VLMEvalKit 的 TSV 格式）"])
    option_cols = sorted(c for c in cols if OPTION_COLUMN.match(c))
    records = list(reader)
    by_index = {str(r["index"]): r["image"] for r in records if "index" in r and not _empty(r.get("image")) and len(r["image"]) > 64}

    rows: list[dict] = []
    for n, r in enumerate(records, 2):  # line 1 is the header
        try:
            imgs = _images(r.get("image") or "", by_index) if "image" in cols else []
        except DatasetError as e:
            raise DatasetError([f"第 {n} 行：{e.errors[0]}"]) from None
        question = r["question"].strip()
        if not _empty(r.get("hint")):
            question = f"{r['hint'].strip()}\n{question}"
        extra = {k: r[k] for k in EXTRA_COLUMNS if k in r and not _empty(r[k])}
        if option_cols:
            options = [r[c].strip() for c in option_cols if not _empty(r.get(c))]
            if imgs:
                question = "".join(f"<image {i}> " for i in range(1, len(imgs) + 1)) + question
            row = {"question": question, "options": options, "answer": r["answer"].strip().upper(), **extra}
            row.update({f"image_{i}": u for i, u in enumerate(imgs, 1)})
        else:
            content = [{"type": "image_url", "image_url": {"url": u}} for u in imgs] + [{"type": "text", "text": question}]
            row = {"messages": [{"role": "user", "content": content}], "answer": r["answer"].strip(), **extra}
        rows.append(row)
    if not rows:
        raise DatasetError(["表格里没有任何样本"])
    return rows, "vmcq" if option_cols else "vqa"
