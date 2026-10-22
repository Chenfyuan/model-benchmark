"""Browser tests against the real app (built frontend + API), seeded with finished runs. No worker, no model calls.

Needs: `npm run build` in frontend/, and `pip install playwright` + a Chromium (`playwright install chromium`, or set CHROMIUM_PATH).
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.environ.get("E2E_PORT", "8021"))


@pytest.fixture(scope="session")
def server(tmp_path_factory):
    dist = ROOT / "frontend" / "dist"
    if not dist.is_dir():
        pytest.skip("frontend/dist missing: run `npm run build` in frontend/ first")
    data = tmp_path_factory.mktemp("e2e-data")
    subprocess.run([sys.executable, str(ROOT / "e2e" / "seed.py"), str(data)], check=True, capture_output=True)
    env = {**os.environ, "APP_DATA_DIR": str(data), "FRONTEND_DIST": str(dist)}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT)], cwd=ROOT / "backend", env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{PORT}"
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(url + "/api/v1/runs", timeout=1)
                break
            except OSError:
                time.sleep(0.5)
        else:
            raise RuntimeError("server did not start")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture(scope="session")
def browser():
    sync = pytest.importorskip("playwright.sync_api")
    with sync.sync_playwright() as p:
        exe = os.environ.get("CHROMIUM_PATH")
        b = p.chromium.launch(args=["--no-sandbox"], **({"executable_path": exe} if exe else {}))
        yield b
        b.close()


@pytest.fixture
def page(browser, server):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    pg = ctx.new_page()
    pg.base = server
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.on("console", lambda m: m.type == "error" and "409" not in m.text and pg.errors.append(m.text))  # a 409 is an expected API answer
    yield pg
    assert not pg.errors, pg.errors  # no uncaught exception or console error on any page
    ctx.close()
