"""FastAPI 入口：实验/批次/查看 REST API，并在根路径托管前端构建产物。"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import service
from .db import get_engine
from .models import Base, Batch, BatchVersion, Experiment, View
from .validation import ValidationError, validate_batch_push, validate_experiment_create

STATIC_DIR = Path(os.environ.get("STATIC_DIR", "/app/static"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.environ.get("CREATE_TABLES", "1") == "1":
        Base.metadata.create_all(get_engine())
    yield


app = FastAPI(title="A/B 实验监测系统", version="1.0.0", lifespan=lifespan)


@app.exception_handler(ValidationError)
async def validation_handler(request, exc: ValidationError):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=422, content={"detail": exc.detail})


def _session() -> Session:
    return Session(get_engine(), future=True)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.post("/api/experiments", status_code=201)
def api_create_experiment(payload: dict = Body(...)):
    data = validate_experiment_create(payload)
    with _session() as conn:
        result = service.create_experiment(conn, data)
        conn.commit()
    return result


@app.get("/api/experiments")
def api_list_experiments():
    with _session() as conn:
        rows = conn.execute(select(Experiment).order_by(Experiment.created_at.desc())).scalars()
        return [service.experiment_dict(e) for e in rows]


@app.get("/api/experiments/{experiment_id}")
def api_get_experiment(experiment_id: str):
    with _session() as conn:
        return service.experiment_dict(service.get_experiment(conn, experiment_id))


@app.post("/api/experiments/{experiment_id}/batches")
def api_push_batch(experiment_id: str, payload: dict = Body(...)):
    data = validate_batch_push(payload)
    with _session() as conn:
        result = service.upsert_batch(conn, experiment_id, data)
        conn.commit()
    return result


@app.get("/api/experiments/{experiment_id}/batches")
def api_list_batches(experiment_id: str):
    with _session() as conn:
        service.get_experiment(conn, experiment_id)
        rows = conn.execute(
            select(Batch).where(Batch.experiment_id == experiment_id)
            .order_by(Batch.batch_no)
        ).scalars()
        return [service.batch_dict(b) for b in rows]


@app.get("/api/experiments/{experiment_id}/corrections")
def api_list_corrections(experiment_id: str):
    with _session() as conn:
        service.get_experiment(conn, experiment_id)
        rows = conn.execute(
            select(BatchVersion).where(BatchVersion.experiment_id == experiment_id)
            .order_by(BatchVersion.batch_no, BatchVersion.version)
        ).scalars()
        return [service.version_dict(v) for v in rows]


@app.post("/api/experiments/{experiment_id}/views", status_code=201)
def api_create_view(experiment_id: str, payload: dict = Body(default={})):
    trigger = payload.get("trigger", "manual") if isinstance(payload, dict) else "manual"
    with _session() as conn:
        result = service.perform_view(conn, experiment_id, trigger)
        conn.commit()
    return result


@app.get("/api/experiments/{experiment_id}/views")
def api_list_views(experiment_id: str):
    with _session() as conn:
        service.get_experiment(conn, experiment_id)
        rows = conn.execute(
            select(View).where(View.experiment_id == experiment_id).order_by(View.seq)
        ).scalars()
        return [service.view_dict(v) for v in rows]


@app.get("/api/experiments/{experiment_id}/trajectory")
def api_trajectory(experiment_id: str):
    """轨迹 + 已发生查看的边界点。边界只在「计划查看点」上定义，
    因此以已发生查看序列逐点返回；前端按步进折线叠加。"""
    with _session() as conn:
        exp = service.get_experiment(conn, experiment_id)
        rows = conn.execute(
            select(View).where(View.experiment_id == experiment_id).order_by(View.seq)
        ).scalars().all()
        points = [service.view_dict(v) for v in rows]
        alpha = float(exp.alpha)
        return {
            "experiment_id": experiment_id,
            "status": exp.status,
            "conclusion": exp.conclusion,
            "n_per_group": exp.n_per_group,
            "fixed_boundary": 1.959963984540054,
            "total_alpha": alpha,
            "points": points,
        }


@app.post("/api/experiments/{experiment_id}/replay")
def api_replay(experiment_id: str):
    with _session() as conn:
        return service.replay(conn, experiment_id)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# 前端静态资源（/api 之外全部回退到 SPA）
# ---------------------------------------------------------------------------

if STATIC_DIR.is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=STATIC_DIR / "assets"),
        name="assets",
    )

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        if full_path.startswith("api/"):
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="not found")
        candidate = STATIC_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")
