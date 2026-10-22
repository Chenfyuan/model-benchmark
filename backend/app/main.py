from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import errors
from .config import get_settings
from .db import SessionLocal, init_db
from .routers import compare, datasets, models, runs, settings
from .services.catalog import seed_builtin


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with SessionLocal() as db:
        seed_builtin(db)
    yield


app = FastAPI(title="多模态模型评测平台", version="0.1.0", lifespan=lifespan)
errors.install(app)
# the Vite dev server runs on another port; the built front end is served from this app (same origin)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])

api = APIRouter(prefix="/api/v1")
api.include_router(models.router)
api.include_router(datasets.router)
api.include_router(runs.router)
api.include_router(compare.router)
api.include_router(settings.router)


@api.get("/health")
def health():
    return {"status": "ok"}


app.include_router(api)

_dist = get_settings().frontend_dist
if _dist.is_dir():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):  # client-side routes fall back to index.html
        f = (_dist / path).resolve()
        if path and _dist.resolve() in f.parents and f.is_file():
            return FileResponse(f)
        return FileResponse(_dist / "index.html")
