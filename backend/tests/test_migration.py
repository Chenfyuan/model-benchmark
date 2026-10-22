"""Databases created before a column existed must keep working (additive migration)."""
import sqlalchemy as sa

from app import db as db_module
from app import models  # noqa: F401  (register tables)

NEW_RUN_COLUMNS = ["input_tokens", "output_tokens", "cost", "stop_reason", "resume", "reused_samples", "attempts"]


def test_ensure_columns_adds_missing_nullable_columns(tmp_path, monkeypatch):
    eng = sa.create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    db_module.Base.metadata.create_all(eng)
    with eng.begin() as c:  # turn it into an "old" database: today's schema minus the columns added later
        for col in NEW_RUN_COLUMNS:
            c.execute(sa.text(f"ALTER TABLE run DROP COLUMN {col}"))
        c.execute(sa.text("INSERT INTO model_endpoint (id, name, protocol, base_url, model_name, api_key_enc, api_key_hint, created_at) "
                          "VALUES (1, 'm', 'openai', 'http://x', 'm', 'enc', '****', '2026-01-01')"))
        c.execute(sa.text("INSERT INTO dataset (id, name, version, source, kind, description, verified, created_at) "
                          "VALUES (1, 'd', 1, 'custom', 'vqa', '', 0, '2026-01-01')"))
        c.execute(sa.text("INSERT INTO run (id, model_id, dataset_id, status, stage, progress, cancel_requested, config, engine, created_at) "
                          "VALUES (1, 1, 1, 'completed', 'done', 1.0, 0, '{}', 'evalscope', '2026-01-01')"))
    assert not {"input_tokens"} & {c["name"] for c in sa.inspect(eng).get_columns("run")}
    monkeypatch.setattr(db_module, "engine", eng)

    db_module.ensure_columns()

    assert set(NEW_RUN_COLUMNS) <= {c["name"] for c in sa.inspect(eng).get_columns("run")}
    with eng.connect() as c:
        row = c.execute(sa.text("SELECT status, input_tokens, resume, attempts FROM run WHERE id = 1")).one()
    assert tuple(row) == ("completed", None, None, None)  # the old row is intact; new columns are simply empty

    db_module.ensure_columns()  # idempotent


def test_old_rows_are_served_by_the_api(client, model, vmcq_dataset):
    """A run whose new columns are NULL (as after the migration) must serialise with sensible defaults."""
    from sqlalchemy import update

    from app.db import SessionLocal
    from app.models import Run

    r = client.post("/api/v1/runs", json={"model_ids": [model["id"]], "dataset_ids": [vmcq_dataset["id"]]}).json()[0]
    with SessionLocal() as db:
        db.execute(update(Run).where(Run.id == r["id"]).values(attempts=None, resume=None, input_tokens=None, cost=None))
        db.commit()
    got = client.get(f"/api/v1/runs/{r['id']}").json()
    assert got["attempts"] == 1 and got["input_tokens"] is None and got["cost"] is None and got["stop_reason"] is None
