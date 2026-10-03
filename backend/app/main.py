"""FastAPI 入口：建实验、推批次、查看、轨迹、重放、静态页面托管。"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from . import schemas, service, stats
from .config import settings
from .models import Base, Batch, BatchEvent, Experiment, Look

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


app = FastAPI(title="成组序贯实验监测系统", version="1.0.0")


# --------------------------- 校验错误统一处理 -------------------------------- #


def _value_errors(exc: ValueError) -> list[tuple[str, str]]:
    # Pydantic model_validator 抛出的 ValueError 第一个参数是 [(field, msg), ...]
    args = exc.args
    if args and isinstance(args[0], list):
        out = []
        for item in args[0]:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                out.append((str(item[0]), str(item[1])))
        if out:
            return out
    return [("body", str(exc))]


@app.exception_handler(service.NotFoundError)
def _not_found(request: Request, exc: service.NotFoundError):
    return JSONResponse(status_code=404, content={"error": "not_found", "detail": str(exc)})


@app.exception_handler(service.ConflictError)
def _conflict(request: Request, exc: service.ConflictError):
    return JSONResponse(
        status_code=409,
        content={
            "error": "conflict",
            "detail": str(exc),
            "fields": [{"field": f, "message": m} for f, m in exc.fields],
        },
    )


def _loc_to_field(err: dict) -> str:
    loc = [str(x) for x in err.get("loc", []) if x not in ("body",)]
    return ".".join(loc) if loc else "body"


@app.exception_handler(RequestValidationError)
def _validation_error(request: Request, exc: RequestValidationError):
    fields: list[dict[str, str]] = []
    for err in exc.errors():
        msg = err.get("msg", "参数无效")
        # model_validator 抛出的 ValueError(errs) 会被 pydantic 包装，
        # ctx.error.args[0] 是 [(field, message), ...]
        ctx = err.get("ctx") or {}
        inner = ctx.get("error")
        extracted = False
        if isinstance(inner, ValueError) and inner.args and isinstance(inner.args[0], list):
            for item in inner.args[0]:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    fields.append({"field": str(item[0]), "message": str(item[1])})
                    extracted = True
        if not extracted:
            fields.append({"field": _loc_to_field(err), "message": msg})
    return JSONResponse(
        status_code=422,
        content={"error": "validation_failed", "detail": "输入校验失败", "fields": fields},
    )


# ------------------------------- 实验 --------------------------------------- #


def _get_experiment_or_404(db: Session, experiment_id: int) -> Experiment:
    exp = db.get(Experiment, experiment_id)
    if exp is None:
        raise service.NotFoundError(f"实验 {experiment_id} 不存在")
    return exp


def _experiment_out(exp: Experiment, db: Session) -> schemas.ExperimentOut:
    totals = service.current_totals(db, exp.id)
    t_eff, raw, clip = stats.info_time(
        totals.control_visits, totals.treatment_visits, exp.planned_n_per_group
    )
    looks_count = db.scalar(
        select(func.count(Look.id)).where(Look.experiment_id == exp.id)
    )
    return schemas.ExperimentOut(
        id=exp.id,
        name=exp.name,
        control_label=exp.control_label,
        treatment_label=exp.treatment_label,
        baseline_rate=exp.baseline_rate,
        target_rate=exp.target_rate,
        alpha=exp.alpha,
        power=exp.power,
        min_effect_abs=exp.min_effect_abs,
        planned_n_per_group=exp.planned_n_per_group,
        freeze_past_looks=exp.freeze_past_looks,
        concluded=exp.concluded,
        created_at=exp.created_at,
        control_visits=totals.control_visits,
        control_conversions=totals.control_conversions,
        treatment_visits=totals.treatment_visits,
        treatment_conversions=totals.treatment_conversions,
        current_info_time=t_eff,
        raw_info_time=raw,
        info_clipped=clip,
        looks_done=int(looks_count or 0),
    )


@app.post("/api/experiments", response_model=schemas.ExperimentOut, status_code=201)
def create_experiment(payload: schemas.ExperimentCreate, db: Session = Depends(get_db)):
    n = stats.sample_size_per_group(
        payload.baseline_rate, payload.target_rate, payload.alpha, payload.power
    )
    exp = Experiment(
        name=payload.name,
        control_label=payload.control_label,
        treatment_label=payload.treatment_label,
        baseline_rate=payload.baseline_rate,
        target_rate=payload.target_rate,
        alpha=payload.alpha,
        power=payload.power,
        min_effect_abs=abs(payload.target_rate - payload.baseline_rate),
        planned_n_per_group=n,
        freeze_past_looks=True,
    )
    db.add(exp)
    db.commit()
    db.refresh(exp)
    return _experiment_out(exp, db)


@app.get("/api/experiments", response_model=list[schemas.ExperimentOut])
def list_experiments(db: Session = Depends(get_db)):
    exps = list(db.scalars(select(Experiment).order_by(Experiment.id)))
    return [_experiment_out(e, db) for e in exps]


@app.get("/api/experiments/{experiment_id}", response_model=schemas.ExperimentOut)
def get_experiment(experiment_id: int, db: Session = Depends(get_db)):
    return _experiment_out(_get_experiment_or_404(db, experiment_id), db)


# ------------------------------- 批次 --------------------------------------- #


def _batch_out(b: Batch) -> schemas.BatchOut:
    return schemas.BatchOut(
        batch_no=b.batch_no,
        control_visits=b.control_visits,
        control_conversions=b.control_conversions,
        treatment_visits=b.treatment_visits,
        treatment_conversions=b.treatment_conversions,
        correction_count=b.correction_count,
        first_received_at=b.first_received_at,
        last_updated_at=b.last_updated_at,
        received_seq=b.received_seq,
    )


@app.post(
    "/api/experiments/{experiment_id}/batches",
    response_model=dict,
    responses={409: {"model": schemas.HTTPError}, 404: {"model": schemas.HTTPError}},
)
def push_batch(
    experiment_id: int, payload: schemas.BatchPush, db: Session = Depends(get_db)
):
    exp = _get_experiment_or_404(db, experiment_id)
    result = service.push_batch(db, exp, payload)
    db.commit()
    return {
        "status": result["status"],
        "batch": _batch_out(result["batch"]).model_dump(mode="json"),
        "event_id": result["event"].id,
        "message": {
            "insert": "批次已入库",
            "correction": "批次已更正；历史查看按冻结策略保留，更正只影响后续查看",
            "duplicate_ignored": "同批次号重复推送，已幂等忽略",
        }[result["status"]],
    }


@app.get(
    "/api/experiments/{experiment_id}/batches",
    response_model=list[schemas.BatchOut],
)
def list_batches(experiment_id: int, db: Session = Depends(get_db)):
    _get_experiment_or_404(db, experiment_id)
    rows = db.scalars(
        select(Batch)
        .where(Batch.experiment_id == experiment_id)
        .order_by(Batch.received_seq, Batch.batch_no)
    ).all()
    return [_batch_out(b) for b in rows]


@app.get(
    "/api/experiments/{experiment_id}/events",
    response_model=list[schemas.BatchEventOut],
)
def list_events(experiment_id: int, db: Session = Depends(get_db)):
    _get_experiment_or_404(db, experiment_id)
    rows = db.scalars(
        select(BatchEvent)
        .where(BatchEvent.experiment_id == experiment_id)
        .order_by(BatchEvent.id)
    ).all()
    return [
        schemas.BatchEventOut(
            id=r.id,
            batch_no=r.batch_no,
            event_type=r.event_type,
            control_visits=r.control_visits,
            control_conversions=r.control_conversions,
            treatment_visits=r.treatment_visits,
            treatment_conversions=r.treatment_conversions,
            prior_control_visits=r.prior_control_visits,
            prior_control_conversions=r.prior_control_conversions,
            prior_treatment_visits=r.prior_treatment_visits,
            prior_treatment_conversions=r.prior_treatment_conversions,
            note=r.note,
            created_at=r.created_at,
        )
        for r in rows
    ]


# ------------------------------- 查看 --------------------------------------- #


def _look_out(lk: Any) -> schemas.LookOut:
    return schemas.LookOut(
        look_number=lk.look_number,
        trigger=lk.trigger,
        raw_info_time=lk.raw_info_time,
        info_time=lk.info_time,
        clipped=lk.clipped,
        control_visits=lk.control_visits,
        control_conversions=lk.control_conversions,
        treatment_visits=lk.treatment_visits,
        treatment_conversions=lk.treatment_conversions,
        z_stat=lk.z_stat,
        boundary=lk.boundary,
        cumulative_spend=lk.cumulative_spend,
        decision=lk.decision,
        correction_since_last=lk.correction_since_last,
        based_on_event_id=lk.based_on_event_id,
        created_at=lk.created_at,
    )


@app.post(
    "/api/experiments/{experiment_id}/looks",
    response_model=schemas.LookCreateResponse,
)
def create_look(
    experiment_id: int,
    payload: schemas.LookTrigger | None = None,
    db: Session = Depends(get_db),
):
    trigger = payload.trigger if payload is not None else "manual"
    exp = _get_experiment_or_404(db, experiment_id)
    result = service.perform_look(db, exp, trigger=trigger)
    db.commit()
    return schemas.LookCreateResponse(
        created=True, look=_look_out(result["look"]), correction_warning=result["warning"]
    )


@app.get("/api/experiments/{experiment_id}/looks", response_model=list[schemas.LookOut])
def list_looks(experiment_id: int, db: Session = Depends(get_db)):
    _get_experiment_or_404(db, experiment_id)
    rows = db.scalars(
        select(Look).where(Look.experiment_id == experiment_id).order_by(Look.look_number)
    ).all()
    return [_look_out(lk) for lk in rows]


@app.post(
    "/api/experiments/{experiment_id}/replay",
    response_model=schemas.ReplayReport,
)
def replay(experiment_id: int, db: Session = Depends(get_db)):
    exp = _get_experiment_or_404(db, experiment_id)
    report = service.replay_experiment(db, exp)
    return schemas.ReplayReport(
        experiment_id=exp.id,
        events_replayed=report["events_replayed"],
        looks_replayed=report["looks_replayed"],
        looks=[_look_out(lk) for lk in report["looks"]],
        match=report["match"],
        discrepancies=report["discrepancies"],
        control_visits=report["totals"].control_visits,
        control_conversions=report["totals"].control_conversions,
        treatment_visits=report["totals"].treatment_visits,
        treatment_conversions=report["totals"].treatment_conversions,
    )


@app.get("/api/experiments/{experiment_id}/trajectory", response_model=schemas.TrajectoryOut)
def trajectory(experiment_id: int, db: Session = Depends(get_db)):
    exp = _get_experiment_or_404(db, experiment_id)
    rows = list(
        db.scalars(
            select(Look)
            .where(Look.experiment_id == experiment_id)
            .order_by(Look.look_number)
        )
    )
    points = [
        schemas.TrajectoryPoint(
            look_number=lk.look_number,
            info_time=lk.info_time,
            raw_info_time=lk.raw_info_time,
            z_stat=lk.z_stat,
            boundary=lk.boundary,
            lower_boundary=-lk.boundary,
            decision=lk.decision,
            trigger=lk.trigger,
            created_at=lk.created_at,
            clipped=lk.clipped,
        )
        for lk in rows
    ]
    # 计划预览：10 个等距信息时点的 LD-OBF 边界与累计消耗（不实际消耗 alpha）
    preview_ts = tuple(round(0.1 * i, 2) for i in range(1, 11))
    bs = stats.boundaries_cached(preview_ts, exp.alpha)
    planned = [
        {
            "info_time": t,
            "boundary": b,
            "lower_boundary": -b,
            "cumulative_spend": stats.alpha_spend(t, exp.alpha),
        }
        for t, b in zip(preview_ts, bs)
    ]
    return schemas.TrajectoryOut(
        planned_n_per_group=exp.planned_n_per_group,
        alpha=exp.alpha,
        freeze_past_looks=exp.freeze_past_looks,
        points=points,
        planned_preview=planned,
    )


@app.get("/api/health")
def health():
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return {"status": "ok"}
    except Exception as exc:  # pragma: no cover
        return JSONResponse(status_code=503, content={"status": "degraded", "detail": str(exc)})


# --------------------------- 自动查看后台任务 ------------------------------- #


async def _auto_look_loop():
    interval = settings.auto_look_interval_seconds
    if interval <= 0:
        return
    while True:
        await asyncio.sleep(interval)
        try:
            db = SessionLocal()
            try:
                exp_ids = list(db.scalars(select(Experiment.id).where(Experiment.concluded == False)))  # noqa: E712
                for eid in exp_ids:
                    exp = db.get(Experiment, eid)
                    try:
                        service.perform_look(db, exp, trigger="scheduled")
                        db.commit()
                    except service.ConflictError:
                        db.rollback()
            finally:
                db.close()
        except Exception:  # pragma: no cover
            await asyncio.sleep(1)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    task = asyncio.create_task(_auto_look_loop())
    try:
        yield
    finally:
        task.cancel()


app.router.lifespan_context = lifespan


# ----------------------------- 静态页面托管 --------------------------------- #

if os.path.isdir(settings.static_dir):
    app.mount(
        "/assets",
        StaticFiles(directory=os.path.join(settings.static_dir, "assets")),
        name="assets",
    )

    @app.get("/")
    def index():
        return FileResponse(os.path.join(settings.static_dir, "index.html"))

    @app.get("/favicon.svg")
    def favicon():
        p = os.path.join(settings.static_dir, "favicon.svg")
        if os.path.exists(p):
            return FileResponse(p)
        return JSONResponse(status_code=404, content={"error": "not_found"})
