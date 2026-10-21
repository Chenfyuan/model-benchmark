"""Runtime settings, read from environment variables once per process."""
from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings:
    def __init__(self) -> None:
        self.data_dir = Path(os.environ.get("APP_DATA_DIR", REPO_ROOT / "backend" / "data")).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir = self.data_dir / "runs"
        self.datasets_dir = self.data_dir / "datasets"
        self.runs_dir.mkdir(exist_ok=True)
        self.datasets_dir.mkdir(exist_ok=True)

        self.database_url = os.environ.get("DATABASE_URL", f"sqlite:///{self.data_dir / 'app.db'}")
        self.max_upload_mb = int(os.environ.get("MAX_UPLOAD_MB", "100"))
        self.run_timeout_sec = int(os.environ.get("RUN_TIMEOUT_SEC", str(6 * 3600)))
        self.worker_poll_sec = float(os.environ.get("WORKER_POLL_SEC", "2"))
        self.frontend_dist = Path(os.environ.get("FRONTEND_DIST", REPO_ROOT / "frontend" / "dist"))

    def secret_key(self) -> bytes:
        """Fernet key used to encrypt model API keys at rest.

        Taken from APP_SECRET_KEY, otherwise generated once into <data_dir>/secret.key (mode 600).
        """
        env = os.environ.get("APP_SECRET_KEY")
        if env:
            return env.encode()
        path = self.data_dir / "secret.key"
        if not path.exists():
            from cryptography.fernet import Fernet

            path.write_bytes(Fernet.generate_key())
            path.chmod(0o600)
        return path.read_bytes().strip()


@lru_cache
def get_settings() -> Settings:
    return Settings()


def new_token() -> str:
    return secrets.token_hex(8)
