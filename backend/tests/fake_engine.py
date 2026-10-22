"""A stand-in engine for tests: same config / progress / collect code as EvalScope, but the subprocess just
copies recorded real EvalScope output (tests/fixtures) into place instead of calling any model."""
from __future__ import annotations

import os
import sys

from app.engines.base import Prepared, RunContext
from app.engines.evalscope_adapter import EvalScopeAdapter
from conftest import FIXTURES

COPY_SCRIPT = """
import os, pathlib, shutil
dst = pathlib.Path(os.environ['OUT'])
shutil.copytree(os.environ['FIX'], dst)
imgdir = os.environ.get('IMGDIR')
if imgdir:
    for f in dst.rglob('*.jsonl'):
        f.write_text(f.read_text().replace('/DATA/data/img', imgdir))
print('Evaluating[x]: 100%|##########| 2/2 [00:01<00:00,  1.00it/s]')
"""
FAIL_SCRIPT = "import os, sys; print('boom: key was ' + os.environ['EVAL_API_KEY']); sys.exit(1)"
TRANSIENT_SCRIPT = "import sys; print('openai.InternalServerError: Error code: 503 - No available accounts'); sys.exit(1)"
SLEEP_SCRIPT = "import time; print('Downloading data: 10%'); time.sleep(120)"

# Behaves like the real EvalScope as measured in the cache experiment: one prediction line is appended per answered sample
# (before scoring), and with use_cache the *same* directory is continued and only the missing samples are "sent".
SLOW_SCRIPT = """
import json, os, pathlib, shutil, time
cfg = json.load(open(os.environ['TASK_JSON']))
n, delay = int(os.environ['FAKE_N']), float(os.environ['FAKE_DELAY'])
out = pathlib.Path(cfg['use_cache']) if cfg.get('use_cache') else pathlib.Path(cfg['work_dir']) / '20260101_000000'
pred = out / 'predictions' / 'm' / 'general_vmcq_demo.jsonl'
pred.parent.mkdir(parents=True, exist_ok=True)
have = sum(1 for _ in open(pred)) if pred.exists() else 0
for i in range(have, n):
    time.sleep(delay)
    with open(os.environ['FAKE_CALLS'], 'a') as c:   # one line per request the "model" actually received
        c.write('1\\n')
    with open(pred, 'a') as f:
        f.write(json.dumps({'index': i, 'model_output': {'usage': {'input_tokens': 1000, 'output_tokens': 10}}}) + '\\n')
        f.flush()
shutil.copytree(os.environ['FIX'], out, dirs_exist_ok=True)   # reports + reviews appear only at the very end
print('Evaluating[x]: 100%|##########| 2/2 [00:01<00:00,  1.00it/s]')
"""


class FakeAdapter(EvalScopeAdapter):
    def __init__(self, mode: str = "ok", fixture: str = "general_vmcq", imgdir: str | None = None,
                 n: int = 10, delay: float = 0.4, calls_file: str | None = None):
        self.mode, self.fixture, self.imgdir = mode, fixture, imgdir
        self.n, self.delay, self.calls_file = n, delay, calls_file

    def prepare(self, ctx: RunContext) -> Prepared:
        prepared = super().prepare(ctx)  # exercises the real config writing
        script = {"ok": COPY_SCRIPT, "fail": FAIL_SCRIPT, "sleep": SLEEP_SCRIPT, "slow": SLOW_SCRIPT, "transient": TRANSIENT_SCRIPT}[self.mode]
        env = dict(prepared.env)
        env.update(TASK_JSON=str(ctx.work_dir / "task.json"), FAKE_N=str(self.n), FAKE_DELAY=str(self.delay),
                   FAKE_CALLS=self.calls_file or str(ctx.work_dir.parent / "calls.log"))
        env["FIX"] = str(FIXTURES / self.fixture)
        env["OUT"] = str(ctx.work_dir / "out" / "20260101_000000")
        if self.imgdir:
            env["IMGDIR"] = self.imgdir
        return Prepared(cmd=[sys.executable, "-c", script], env=env, cwd=prepared.cwd, log_path=prepared.log_path)
