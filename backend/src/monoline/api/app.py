"""FastAPI app — the product body.

Startup: connect the Repo + start the JobManager (background pipeline worker).
Mounts: /api/* (jobs + health), /w/{job}/… (composition assets, containment-checked,
for <hyperframes-player>), and the built SPA at /.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..doctor import run_doctor
from ..queue.manager import JobManager
from ..settings import get_settings
from .routes_jobs import router as jobs_router
from .routes_meta import router as meta_router
from .routes_script import router as script_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    manager = JobManager(settings)
    await manager.start()
    app.state.manager = manager
    app.state.settings = settings
    try:
        yield
    finally:
        await manager.stop()


app = FastAPI(title="Monoline", version="0.1.0", lifespan=lifespan)
app.include_router(jobs_router)
app.include_router(script_router)
app.include_router(meta_router)


@app.get("/api/health")
async def health() -> JSONResponse:
    settings = get_settings()
    # run_doctor shells out to node/hyperframes — keep it off the event loop so a
    # slow probe can't freeze the whole server.
    doc = await asyncio.to_thread(run_doctor, settings)
    return JSONResponse({"app": "monoline", "version": app.version, "port": settings.port, **doc})


# --- composition workspace mount: /w/{job}/<rel> → workspaces/{job}/composition/<rel>
# Containment-checked; serves only inside composition/, never app.db/input/logs.
@app.get("/w/{job_id}/{rel:path}")
async def workspace_file(job_id: str, rel: str):
    settings = get_settings()
    comp_root = (settings.workspaces_dir / job_id / "composition").resolve()
    target = (comp_root / rel).resolve()
    if not str(target).startswith(str(comp_root)) or not target.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(target)


# --- SPA (built web/dist copied into static_dir by `monoline start`) ----------
class SpaStatic(StaticFiles):
    """index.html must never be cached. A stale bundle is exactly "I clicked and nothing
    happened" — the assets it references are content-hashed, so those stay cacheable."""

    async def get_response(self, path, scope):  # type: ignore[override]
        resp = await super().get_response(path, scope)
        ctype = resp.headers.get("content-type", "")
        if path.endswith(".html") or ctype.startswith("text/html"):
            resp.headers["cache-control"] = "no-store"
        return resp


settings = get_settings()
static = settings.static_dir
if static.exists() and (static / "index.html").exists():
    app.mount("/", SpaStatic(directory=str(static), html=True), name="spa")
else:
    @app.get("/")
    async def spa_placeholder() -> JSONResponse:
        return JSONResponse({"app": "monoline", "note": "frontend not built yet — run `make start`"})
