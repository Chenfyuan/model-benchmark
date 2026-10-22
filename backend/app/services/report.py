"""Self-contained HTML reports (one file, no external assets) for sharing a run or a model comparison."""
from __future__ import annotations

import base64
import mimetypes
from datetime import datetime
from html import escape
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Run, RunMetric, SampleResult
from ..worker import run_dir
from .rescoring import adjusted_scores, final_verdict

MAX_WRONG = 40          # wrong answers listed per run
MAX_DISAGREE = 30       # questions listed in a comparison
MAX_IMAGE_BYTES = 400_000
CSS = """
body{font:15px/1.6 -apple-system,Segoe UI,Helvetica,Arial,"PingFang SC","Microsoft YaHei",sans-serif;color:#1f2430;background:#f5f6fa;margin:0}
.wrap{max-width:1040px;margin:0 auto;padding:32px 20px 60px}
h1{font-size:26px;margin:0 0 4px} h2{font-size:18px;margin:34px 0 12px} .muted{color:#6b7280;font-size:13.5px}
.card{background:#fff;border:1px solid #e5e7ef;border-radius:12px;padding:18px 20px;margin:12px 0}
.hero{background:linear-gradient(135deg,#5b5bd6,#7c6cf0);color:#fff;border-radius:14px;padding:22px 26px;margin:18px 0}
.hero .v{font-size:54px;font-weight:700;line-height:1.1} .hero .s{opacity:.9;font-size:14px}
table{border-collapse:collapse;width:100%;font-size:14px} th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #eceef5;vertical-align:top}
th{color:#6b7280;font-weight:600;background:#fafbfe} td.num{font-variant-numeric:tabular-nums} .win{background:#e4f6ef;color:#0b7a53;font-weight:600;border-radius:6px}
.tag{display:inline-block;font-size:12px;padding:1px 8px;border-radius:999px;background:#eef0fb;color:#4a4ab5;margin-left:6px}
.warn{background:#fff7e6;border:1px solid #ffd591;border-radius:10px;padding:10px 14px;margin:10px 0;font-size:14px}
.q{border:1px solid #e5e7ef;border-radius:12px;background:#fff;margin:12px 0;overflow:hidden}
.q .h{padding:8px 16px;background:#fafbfe;border-bottom:1px solid #eceef5;font-size:13px;color:#6b7280;display:flex;justify-content:space-between}
.q .b{padding:14px 16px;display:flex;gap:16px} .q img{max-width:220px;max-height:200px;border-radius:8px;border:1px solid #e5e7ef;flex:none}
pre{white-space:pre-wrap;word-break:break-word;margin:4px 0 0;font:13px/1.55 ui-monospace,Menlo,Consolas,monospace}
.ans{border-left:4px solid #cbd0de;background:#fafbfe;padding:6px 10px;border-radius:6px;margin:6px 0;font-size:14px}
.ans.good{border-color:#18a874;background:#effaf5} .ans.bad{border-color:#e5484d;background:#fff1f1}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}
.lab{font-size:12px;color:#6b7280;margin-top:8px} footer{margin-top:40px;color:#9aa0b2;font-size:12.5px}
@media print{body{background:#fff}.card,.q{break-inside:avoid}}
"""


def _fmt_metric(m: RunMetric) -> str:
    return "-" if m.value is None else f"{m.value * (m.display_multiplier or 1.0):.{m.precision}f}{m.display_unit}"


def _page(title: str, body: str) -> str:
    stamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    return (f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{escape(title)}</title><style>{CSS}</style></head><body><div class=\"wrap\">{body}"
            f"<footer>由评测平台生成于 {stamp}。得分来自评测引擎，标注“复核”的是宽松匹配或人工改判后的结果，引擎原始得分始终保留。</footer></div></body></html>")


def _img(run_id: int, s: SampleResult) -> str:
    base = run_dir(run_id).resolve()
    out = []
    for m in (s.media or [])[:2]:
        if m.get("type") != "image":
            continue
        if m.get("kind") == "url":
            out.append(f'<img src="{escape(m["ref"], quote=True)}" alt="">')
        elif m.get("kind") == "file":
            path = (base / m["ref"]).resolve()
            if base in path.parents and path.is_file() and path.stat().st_size <= MAX_IMAGE_BYTES:
                mime = mimetypes.guess_type(path.name)[0] or "image/png"
                out.append(f'<img src="data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}" alt="">')
    return "".join(out)


def _verdict_tag(s: SampleResult) -> str:
    if s.review_correct is not None:
        return '<span class="tag">人工改判</span>' if s.review_correct != s.is_correct else '<span class="tag">人工确认</span>'
    return '<span class="tag">宽松匹配通过</span>' if s.auto_correct else ""


def _answer(s: SampleResult) -> str:
    if s.tool_calls:
        return "\n".join(f"{t.get('name')}({t.get('arguments')})" for t in s.tool_calls)
    return s.prediction or "（空）"


def _run_facts(r: Run) -> str:
    cfg = r.config or {}
    parts = [f"评测集 {escape(r.dataset.name)} v{r.dataset.version}", f"引擎 {escape(r.engine)} {escape(r.engine_version or '')}",
             "全量" if not r.limit else f"每个子集 {r.limit} 题（试跑）",
             f"并发 {cfg.get('batch_size')} · 最大输出 {cfg.get('max_tokens')} · 温度 {cfg.get('temperature')}"]
    if r.judge_model:
        parts.append(f"裁判模型 {escape(r.judge_model.name)}")
    if (r.attempts or 1) > 1:
        parts.append(f"第 {r.attempts} 次尝试（重试时跳过了 {r.reused_samples or 0} 个已完成的样本）")
    return " · ".join(parts)


def _usage_line(r: Run) -> str:
    if r.input_tokens is None:
        return ""
    cost = "未填写单价" if r.cost is None else f"约 ${r.cost:.4f}"
    return f"累计用量 {(r.input_tokens or 0) + (r.output_tokens or 0):,} token（输入 {r.input_tokens:,} / 输出 {r.output_tokens or 0:,}），费用 {cost}"


def run_report(db: Session, r: Run) -> str:
    metrics = db.scalars(select(RunMetric).where(RunMetric.run_id == r.id).order_by(RunMetric.id)).all()
    primary = next((m for m in metrics if m.primary and m.subset == "OVERALL"), None)
    adj = adjusted_scores(db, r.id)
    samples = db.scalars(select(SampleResult).where(SampleResult.run_id == r.id).order_by(SampleResult.subset, SampleResult.idx)).all()
    wrong = [s for s in samples if final_verdict(s) is False and not s.error]
    errors = [s for s in samples if s.error]
    body = [f"<h1>{escape(r.model.name)} × {escape(r.dataset.name)}</h1>",
            f'<div class="muted">任务 #{r.id} · {escape(_run_facts(r))}</div>']
    if primary:
        sub = f"{escape(primary.key)} · {primary.num} 题"
        if adj:
            sub += f' · 复核后 <b>{escape(adj["display"])}</b>（宽松匹配 {adj["n_lenient"]} 题、人工改判 {adj["n_manual"]} 题）'
        body.append(f'<div class="hero"><div class="s">{escape(primary.label)} · 引擎主指标</div><div class="v">{escape(_fmt_metric(primary))}</div><div class="s">{sub}</div></div>')
    if r.limit:
        body.append('<div class="warn">这是限制了题数的试跑，样本少、分数波动大，不能和公开榜单的成绩比较。</div>')
    quality = [m for m in metrics if m.kind == "quality"]
    if quality:
        subsets = list(dict.fromkeys(m.subset for m in quality if m.subset != "OVERALL"))
        keys = list(dict.fromkeys((m.key, m.label) for m in quality))
        head = "".join(f"<th>{escape(label)}</th>" for _, label in keys)
        rows = []
        for sub in subsets + ["OVERALL"]:
            cells = "".join(f'<td class="num">{escape(_fmt_metric(next((m for m in quality if m.key == k and m.subset == sub), None)) if any(m.key == k and m.subset == sub for m in quality) else "—")}</td>' for k, _ in keys)
            rows.append(f"<tr><td>{'合计' if sub == 'OVERALL' else escape(sub)}</td>{cells}</tr>")
        body.append(f'<h2>得分</h2><div class="card"><table><tr><th>子集</th>{head}</tr>{"".join(rows)}</table></div>')
    perf = [m for m in metrics if m.kind == "perf" and m.key in ("latency_mean", "latency_p90", "latency_max", "input_tokens_mean", "output_tokens_mean", "output_tps")]
    if perf or r.input_tokens is not None:
        body.append('<h2>成本与性能</h2><div class="card"><table>' + "".join(f"<tr><th>{escape(m.label)}</th><td class=\"num\">{escape(_fmt_metric(m))}</td></tr>" for m in perf)
                    + (f'<tr><th>用量与费用</th><td>{escape(_usage_line(r))}</td></tr>' if r.input_tokens is not None else "") + "</table></div>")
    body.append(f"<h2>答错的题（共 {len(wrong)} 题" + (f"，显示前 {MAX_WRONG} 题" if len(wrong) > MAX_WRONG else "") + "）</h2>")
    if not wrong:
        body.append('<div class="card muted">没有答错的题。</div>')
    for s in wrong[:MAX_WRONG]:
        note = f'<div class="lab">复核备注</div><div class="ans">{escape(s.review_note)}</div>' if s.review_note else ""
        judge = f'<div class="lab">裁判</div><pre>{escape(s.judge_output)}</pre>' if s.judge_output else ""
        body.append(f'<div class="q"><div class="h"><span>{escape(s.subset)} · #{s.idx}{_verdict_tag(s)}</span><span>引擎判定：{"答对" if s.is_correct else "答错"}</span></div>'
                    f'<div class="b">{_img(r.id, s)}<div style="flex:1;min-width:0"><div class="lab">问题</div><pre>{escape(s.question[:1500])}</pre>'
                    f'<div class="cols"><div><div class="lab">标准答案</div><div class="ans good"><pre>{escape(s.target or "—")}</pre></div></div>'
                    f'<div><div class="lab">模型回答{(" · 抽取：" + escape(s.extracted)) if s.extracted and s.extracted != s.prediction else ""}</div><div class="ans bad"><pre>{escape(_answer(s)[:1500])}</pre></div></div></div>{judge}{note}</div></div></div>')
    if errors:
        body.append(f'<h2>出错的样本（{len(errors)} 题）</h2><div class="card">' + "".join(f"<div>#{s.idx} {escape(s.subset)}：{escape(s.error or '')}</div>" for s in errors[:20]) + "</div>")
    return _page(f"{r.model.name} × {r.dataset.name} 评测报告", "".join(body))


def compare_report(db: Session, runs: list[Run], warnings: list[str]) -> str:
    adj = {r.id: adjusted_scores(db, r.id) for r in runs}
    metrics = {r.id: db.scalars(select(RunMetric).where(RunMetric.run_id == r.id).order_by(RunMetric.id)).all() for r in runs}

    def find(r: Run, key: str, sub: str = "OVERALL") -> RunMetric | None:
        return next((m for m in metrics[r.id] if m.key == key and m.subset == sub), None)

    def row(label: str, pick, direction: str = "none") -> str:
        vals = {r.id: pick(r) for r in runs}
        nums = {i: v[0] for i, v in vals.items() if v and v[0] is not None}
        best = (min if direction == "lower_is_better" else max)(nums.values()) if len(nums) > 1 and direction != "none" else None
        cells = "".join(f'<td class="num{" win" if best is not None and vals[r.id] and abs(vals[r.id][0] - best) < 1e-9 else ""}">{escape(vals[r.id][1]) if vals[r.id] else "—"}</td>' for r in runs)
        return f"<tr><th>{escape(label)}</th>{cells}</tr>"

    head = "".join(f"<th>{escape(r.model.name)}<div class=\"muted\">#{r.id} · {escape(r.dataset.name)} v{r.dataset.version}</div></th>" for r in runs)
    rows = []
    prim_keys = {m.key: m for r in runs for m in metrics[r.id] if m.kind == "quality" and m.subset == "OVERALL"}
    for key, m0 in prim_keys.items():
        rows.append(row(m0.label + (" · 主指标" if m0.primary else ""), lambda r, key=key: (lambda m: (m.value, _fmt_metric(m)) if m else None)(find(r, key)), m0.direction))
    if any(adj.values()):
        rows.append(row("复核后得分（宽松匹配 + 人工）", lambda r: (adj[r.id]["adjusted"], adj[r.id]["display"]) if adj[r.id] else
                        (lambda m: (m.value, _fmt_metric(m) + "（未改判）") if m else None)(next((m for m in metrics[r.id] if m.primary and m.subset == "OVERALL"), None)), "higher_is_better"))
    for key, label, direction in (("latency_mean", "平均延迟", "lower_is_better"), ("latency_p90", "延迟 P90", "lower_is_better"),
                                  ("input_tokens_mean", "平均输入 token", "none"), ("output_tps", "输出吞吐", "higher_is_better")):
        rows.append(row(label, lambda r, key=key: (lambda m: (m.value, _fmt_metric(m)) if m else None)(find(r, key)), direction))
    rows.append(row("累计用量（含重试）", lambda r: None if r.input_tokens is None else ((r.input_tokens or 0) + (r.output_tokens or 0), f"{(r.input_tokens or 0) + (r.output_tokens or 0):,}"), "lower_is_better"))
    rows.append(row("费用", lambda r: None if r.cost is None else (r.cost, f"${r.cost:.4f}"), "lower_is_better"))
    body = ["<h1>模型对比报告</h1>", f'<div class="muted">{len(runs)} 个任务 · 绿色表示这一行最优</div>']
    body += [f'<div class="warn">{escape(w)}</div>' for w in warnings]
    body.append(f'<h2>逐项对比</h2><div class="card"><table><tr><th></th>{head}</tr>{"".join(rows)}</table></div>')

    if len({r.dataset_id for r in runs}) == 1:  # same data: list the questions where the models disagree
        ids = [r.id for r in runs]
        grid: dict[tuple[str, int], dict[int, SampleResult]] = {}
        for s in db.scalars(select(SampleResult).where(SampleResult.run_id.in_(ids))):
            grid.setdefault((s.subset, s.idx), {})[s.run_id] = s
        diff = [k for k, cells in sorted(grid.items()) if len({final_verdict(c) for c in cells.values() if final_verdict(c) is not None}) > 1]
        body.append(f"<h2>模型之间有分歧的题（共 {len(diff)} 题" + (f"，显示前 {MAX_DISAGREE} 题" if len(diff) > MAX_DISAGREE else "") + "）</h2>")
        if not diff:
            body.append('<div class="card muted">所有模型在每道题上的对错一致。</div>')
        for key in diff[:MAX_DISAGREE]:
            cells = grid[key]
            first = next(cells[i] for i in ids if i in cells)
            answers = ""
            for r in runs:
                c = cells.get(r.id)
                if c is None:
                    answers += f'<div><div class="lab">{escape(r.model.name)}</div><div class="ans">无结果</div></div>'
                    continue
                v = final_verdict(c)
                cls = "good" if v else "bad" if v is False else ""
                answers += f'<div><div class="lab">{escape(r.model.name)} · {"答对" if v else "答错" if v is False else "未判定"}{_verdict_tag(c)}</div><div class="ans {cls}"><pre>{escape(_answer(c)[:600])}</pre></div></div>'
            body.append(f'<div class="q"><div class="h"><span>{escape(key[0])} · #{key[1]}</span><span>标准答案：{escape(first.target or "—")}</span></div>'
                        f'<div class="b">{_img(first.run_id, first)}<div style="flex:1;min-width:0"><pre>{escape(first.question[:1200])}</pre><div class="cols">{answers}</div></div></div></div>')
    return _page("模型对比报告", "".join(body))
