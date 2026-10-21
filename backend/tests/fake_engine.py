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
SLEEP_SCRIPT = "import time; print('Downloading data: 10%'); time.sleep(120)"


class FakeAdapter(EvalScopeAdapter):
    def __init__(self, mode: str = "ok", fixture: str = "general_vmcq", imgdir: str | None = None):
        self.mode, self.fixture, self.imgdir = mode, fixture, imgdir

    def prepare(self, ctx: RunContext) -> Prepared:
        prepared = super().prepare(ctx)  # exercises the real config writing
        script = {"ok": COPY_SCRIPT, "fail": FAIL_SCRIPT, "sleep": SLEEP_SCRIPT}[self.mode]
        env = dict(prepared.env)
        env["FIX"] = str(FIXTURES / self.fixture)
        env["OUT"] = str(ctx.work_dir / "out" / "20260101_000000")
        if self.imgdir:
            env["IMGDIR"] = self.imgdir
        return Prepared(cmd=[sys.executable, "-c", script], env=env, cwd=prepared.cwd, log_path=prepared.log_path)
