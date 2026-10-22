import os
import sys
import tempfile
from pathlib import Path

# Must happen before any `app` import: isolated data dir + database for the whole test session.
_tmp = tempfile.mkdtemp(prefix="mb-test-")
os.environ["APP_DATA_DIR"] = _tmp
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.catalog import seed_builtin  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "evalscope"


@pytest.fixture(autouse=True)
def fresh_db():
    import shutil

    from app.config import get_settings

    # run / dataset ids restart at 1 with every fresh database: leftovers on disk from a previous test must not leak in
    for d in (get_settings().runs_dir, get_settings().datasets_dir):
        for child in d.iterdir():
            shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink(missing_ok=True)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_builtin(db)
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


MODEL = dict(name="m1", protocol="openai", base_url="https://api.example.com", model_name="gpt-x", api_key="sk-secret-1234")


@pytest.fixture
def model(client):
    r = client.post("/api/v1/models", json=MODEL)
    assert r.status_code == 201
    return r.json()


VMCQ_ROWS = [
    {"question": "<image 1> Which color?", "options": ["Yellow", "Blue"], "image_1": "https://example.com/a.png", "answer": "B"},
    {"question": "<image 1> Which color?", "options": ["Yellow", "Blue"], "image_1": "https://example.com/b.png", "answer": "A"},
]


@pytest.fixture
def vmcq_dataset(client):
    import json

    body = "\n".join(json.dumps(r) for r in VMCQ_ROWS).encode()
    r = client.post("/api/v1/datasets", data={"name": "colors", "kind": "vmcq"}, files={"file": ("colors.jsonl", body)})
    assert r.status_code == 201, r.text
    return r.json()
