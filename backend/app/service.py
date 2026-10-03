"""业务编排：建实验、批次推送/更正、查看（冻结口径）、重放。

冻结策略（见 docs/stats.md「冻结的代价」一节）：
**已经发生的查看，其信息时间、边界、已消耗 α、结论全部冻结**。批次更正
只改变更正生效之后的查看；即使更正是减量、使当前累计信息比例低于历史
查看点，历史边界也不回退（消耗规则在非递减信息时间  t_k = max历史上沿
上取值，保证 α 累计单调、不超过总 α）。
"""

from __future__ import annotations

import math
import secrets
from typing import Any

from sqlalchemy import Connection, func, select
from sqlalchemy.exc import IntegrityError

from . import stats
from .models import Batch, BatchVersion, Event, Experiment, View
from .validation import ValidationError


# ---------------------------------------------------------------------------
# 序列化
# ---------------------------------------------------------------------------

def _f(v: Any) -> float:
    return float(v) if v is not None else None


def experiment_dict(e: Experiment) -> dict[str, Any]:
    return {
        "id": e.id,
        "name": e.name,
        "baseline_rate": _f(e.baseline_rate),
        "target_rate": _f(e.baseline_rate) + _f(e.mde_abs),
        "mde_abs": _f(e.mde_abs),
        "alpha": _f(e.alpha),
        "power": _f(e.power),
        "spending_rule": e.spending_rule,
        "n_per_group": e.n_per_group,
        "status": e.status,
        "conclusion": e.conclusion,
        "concluded_view_seq": e.concluded_view_seq,
        "created_at": e.created_at.isoformat(),
    }


def view_dict(v: View) -> dict[str, Any]:
    return {
        "seq": v.seq,
        "trigger": v.trigger,
        "total_a_visits": v.total_a_visits,
        "total_a_conv": v.total_a_conv,
        "total_b_visits": v.total_b_visits,
        "total_b_conv": v.total_b_conv,
        "info_fraction_raw": _f(v.info_fraction_raw),
        "info_fraction": _f(v.info_fraction_used),
        "capped": v.capped,
        "z_value": _f(v.z_value),
        "spent_before": _f(v.spent_before),
        "spent_at": _f(v.spent_at),
        "boundary": _f(v.boundary),
        "crossed": v.crossed,
        "conclusion": v.conclusion,
        "created_at": v.created_at.isoformat(),
    }


def batch_dict(b: Batch) -> dict[str, Any]:
    return {
        "batch_no": b.batch_no,
        "group_a_visits": b.group_a_visits,
        "group_a_conv": b.group_a_conv,
        "group_b_visits": b.group_b_visits,
        "group_b_conv": b.group_b_conv,
        "version": b.version,
        "updated_at": b.updated_at.isoformat(),
    }


def version_dict(v: BatchVersion) -> dict[str, Any]:
    return {
        "batch_no": v.batch_no,
        "version": v.version,
        "kind": v.kind,
        "group_a_visits": v.group_a_visits,
        "group_a_conv": v.group_a_conv,
        "group_b_visits": v.group_b_visits,
        "group_b_conv": v.group_b_conv,
        "note": v.note,
        "created_at": v.created_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# 实验
# ---------------------------------------------------------------------------

def create_experiment(conn: Connection, data: dict[str, Any]) -> dict[str, Any]:
    n = stats.sample_size_per_group(
        data["baseline_rate"], data["mde_abs"], data["alpha"], data["power"]
    )
    for _ in range(5):
        eid = "exp" + secrets.token_hex(5)
        exp = Experiment(
            id=eid,
            name=data["name"],
            baseline_rate=data["baseline_rate"],
            mde_abs=data["mde_abs"],
            alpha=data["alpha"],
            power=data["power"],
            spending_rule=data["spending_rule"],
            n_per_group=n,
            status="running",
        )
        conn.add(exp)
        try:
            conn.flush()
        except IntegrityError:  # 极小概率主键撞号，重试
            conn.rollback()
            continue
        return experiment_dict(exp)
    raise RuntimeError("实验 ID 生成连续冲突")  # pragma: no cover


def get_experiment(conn: Connection, experiment_id: str) -> Experiment:
    exp = conn.get(Experiment, experiment_id)
    if exp is None:
        raise ValidationError({"experiment_id": "实验不存在"})
    return exp


# ---------------------------------------------------------------------------
# 批次
# ---------------------------------------------------------------------------

def _current_totals(conn: Connection, exp_id: str) -> tuple[int, int, int, int]:
    rows = conn.execute(
        select(
            Batch.group_a_visits, Batch.group_a_conv,
            Batch.group_b_visits, Batch.group_b_conv,
        ).where(Batch.experiment_id == exp_id)
    ).all()
    return (
        sum(r[0] for r in rows),
        sum(r[1] for r in rows),
        sum(r[2] for r in rows),
        sum(r[3] for r in rows),
    )


def upsert_batch(conn: Connection, experiment_id: str, data: dict[str, Any]) -> dict[str, Any]:
    exp = get_experiment(conn, experiment_id)
    row = conn.execute(
        select(Batch)
        .where(Batch.experiment_id == experiment_id, Batch.batch_no == data["batch_no"])
        .with_for_update()
    ).scalar_one_or_none()

    now_counts = (
        data["group_a_visits"], data["group_a_conv"],
        data["group_b_visits"], data["group_b_conv"],
    )

    latest_view = conn.execute(
        select(View).where(View.experiment_id == experiment_id)
        .order_by(View.seq.desc()).limit(1)
    ).scalar_one_or_none()

    if row is not None:
        old_counts = (row.group_a_visits, row.group_a_conv,
                      row.group_b_visits, row.group_b_conv)
        if old_counts == now_counts:
            return {
                "action": "duplicate_ignored",
                "batch_no": data["batch_no"],
                "version": row.version,
                "message": "相同批次号、相同内容的推送已收到过，本次幂等忽略。",
                **_correction_impact(conn, exp, latest_view, experiment_id),
            }
        row.group_a_visits, row.group_a_conv, row.group_b_visits, row.group_b_conv = now_counts
        row.version += 1
        row.updated_at = func.now()
        ver = BatchVersion(
            experiment_id=experiment_id, batch_no=data["batch_no"],
            version=row.version, kind="correction",
            **{k: data[k] for k in
               ("group_a_visits", "group_a_conv", "group_b_visits", "group_b_conv")},
            note=data.get("note"),
        )
        conn.add(ver)
        conn.flush()
        conn.add(Event(experiment_id=experiment_id, kind="batch", version_id=ver.id))
        action = "corrected"
        version = row.version
    else:
        conn.add(Batch(
            experiment_id=experiment_id, batch_no=data["batch_no"],
            group_a_visits=now_counts[0], group_a_conv=now_counts[1],
            group_b_visits=now_counts[2], group_b_conv=now_counts[3],
            version=1,
        ))
        ver = BatchVersion(
            experiment_id=experiment_id, batch_no=data["batch_no"],
            version=1, kind="push",
            **{k: data[k] for k in
               ("group_a_visits", "group_a_conv", "group_b_visits", "group_b_conv")},
            note=data.get("note"),
        )
        conn.add(ver)
        conn.flush()
        conn.add(Event(experiment_id=experiment_id, kind="batch", version_id=ver.id))
        action = "created"
        version = 1

    conn.flush()
    totals = _current_totals(conn, experiment_id)
    resp = {
        "action": action,
        "batch_no": data["batch_no"],
        "version": version,
        "current_totals": {
            "group_a_visits": totals[0], "group_a_conv": totals[1],
            "group_b_visits": totals[2], "group_b_conv": totals[3],
        },
        **_correction_impact(conn, exp, latest_view, experiment_id),
    }
    if action == "corrected":
        resp["message"] = (
            f"批次 {data['batch_no']} 已更正（第 {version} 版）。"
            + ("该实验结论已冻结，更正不改变历史查看与结论，只影响后续查看。"
               if exp.status == "stopped"
               else "历史查看记录保持冻结，更正只影响后续查看的统计量与边界。")
        )
    return resp


def _correction_impact(conn: Connection, exp: Experiment,
                       latest_view: View | None, exp_id: str) -> dict[str, Any]:
    """更正影响提示用的摘要（在 upsert 内 flush 后调用）。"""
    totals = _current_totals(conn, exp_id)
    changed = False
    if latest_view is not None:
        snap = (latest_view.total_a_visits, latest_view.total_a_conv,
                latest_view.total_b_visits, latest_view.total_b_conv)
        changed = totals != snap
    return {
        "frozen": exp.status == "stopped",
        "changed_since_latest_view": changed,
        "latest_view_seq": latest_view.seq if latest_view else None,
    }


# ---------------------------------------------------------------------------
# 查看
# ---------------------------------------------------------------------------

def _boundary_path(
    prior_times: list[float], prior_spent: list[float],
    t_used: float, alpha: float, spending: str,
) -> tuple[list[float], list[float], float, float]:
    """返回 (times, spent, boundary_now, spent_now)。

    信息时间沿历史非递减包络取值（更正减量不会让时间倒流），保证消耗单调。
    """
    t_env = max([t_used] + prior_times) if prior_times else t_used
    t_env = min(t_env, 1.0)
    times = prior_times + [t_env]
    spent = stats.spent_series(times, alpha, spending)
    boundaries = stats.sequential_boundaries(times, spent)
    return times, spent, boundaries[-1], spent[-1]


def perform_view(conn: Connection, experiment_id: str, trigger: str) -> dict[str, Any]:
    if trigger not in ("manual", "scheduled"):
        raise ValidationError({"trigger": "触发方式只能是 manual 或 scheduled"})
    exp = get_experiment(conn, experiment_id)

    # 锁住实验行，串行化同实验的查看（边界依赖完整查看史）
    conn.execute(
        select(Experiment.id).where(Experiment.id == experiment_id).with_for_update()
    ).all()

    totals = _current_totals(conn, experiment_id)
    na, xa, nb, xb = totals
    if na + nb <= 0:
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail={
            "errors": {"batches": "当前累计访问数为 0，尚无法计算统计量"}
        })
    if na <= 0 or nb <= 0:
        from fastapi import HTTPException
        zero_group = "A" if na <= 0 else "B"
        raise HTTPException(status_code=409, detail={
            "errors": {"batches": f"{zero_group} 组累计访问数为 0，两组比较尚无法计算统计量"}
        })

    prior = conn.execute(
        select(View).where(View.experiment_id == experiment_id).order_by(View.seq)
    ).scalars().all()

    t_raw, capped = stats.information_fraction(na, nb, exp.n_per_group)
    t_used = min(t_raw, 1.0)
    z = stats.z_statistic(na, xa, nb, xb)

    prior_times = [float(v.info_fraction_used) for v in prior]
    prior_spent = [float(v.spent_at) for v in prior]
    times, spent, boundary, spent_now = _boundary_path(
        prior_times, prior_spent, t_used, float(exp.alpha), exp.spending_rule
    )
    t_record = times[-1]  # 落库的信息时间 = 历史非递减包络（更正减量不倒退）
    spent_before = prior_spent[-1] if prior_spent else 0.0

    crossed = abs(z) >= boundary - 1e-12
    if crossed:
        conclusion = "a_wins" if z > 0 else "b_wins"
    else:
        conclusion = "inconclusive"

    seq = (prior[-1].seq + 1) if prior else 1
    view = View(
        experiment_id=experiment_id, seq=seq, trigger=trigger,
        total_a_visits=na, total_a_conv=xa, total_b_visits=nb, total_b_conv=xb,
        info_fraction_raw=t_raw, info_fraction_used=t_record,
        capped=bool(capped), z_value=z,
        spent_before=spent_before, spent_at=spent_now,
        boundary=boundary, crossed=crossed, conclusion=conclusion,
    )
    conn.add(view)
    conn.flush()
    conn.add(Event(experiment_id=experiment_id, kind="view", view_id=view.id))

    warnings: list[str] = []
    if capped:
        warnings.append(
            f"信息比例已达到 {t_raw:.4f}（超过 1），本次按 1 处理。"
        )
    if t_used < t_record - 1e-12:
        warnings.append(
            f"更正使当前累计信息比例回落到 {t_used:.4f}，低于历史查看点 "
            f"{t_record:.4f}；本次信息时间沿历史包络 {t_record:.4f} 取值，"
            "沿用上一边界、不新增 α 消耗（历史查看已冻结）。"
        )
    elif prior_times and abs(t_record - prior_times[-1]) <= 1e-12:
        warnings.append("自上次查看以来信息比例未增加，本次沿用上一边界、不新增 α 消耗。")

    experiment_frozen = exp.status == "stopped"
    if crossed and not experiment_frozen:
        exp.status = "stopped"
        exp.conclusion = conclusion
        exp.concluded_view_seq = seq
    if experiment_frozen:
        warnings.append(
            f"实验已在第 {exp.concluded_view_seq} 次查看越过边界并冻结结论"
            f"（{conclusion_label(exp.conclusion)}）；后续监测不再改写该结论。"
        )

    conn.flush()
    out = view_dict(view)
    out["warnings"] = warnings
    out["experiment_status"] = exp.status
    out["experiment_conclusion"] = exp.conclusion
    return out


def conclusion_label(c: str | None) -> str:
    return {"a_wins": "A 组胜出", "b_wins": "B 组胜出",
            "inconclusive": "未越过边界"}.get(c, "—")


# ---------------------------------------------------------------------------
# 重放
# ---------------------------------------------------------------------------

def replay(conn: Connection, experiment_id: str) -> dict[str, Any]:
    """按 events 全局事件序号从头重放：

    重建每批在每个时间点的生效数据，独立重算每次查看的累计样本、
    信息比例、z、消耗与边界，与落库记录逐项比对。
    """
    exp = get_experiment(conn, experiment_id)
    versions_by_id = {
        v.id: v
        for v in conn.execute(
            select(BatchVersion).where(BatchVersion.experiment_id == experiment_id)
        ).scalars().all()
    }
    views_by_id = {
        v.id: v
        for v in conn.execute(
            select(View).where(View.experiment_id == experiment_id)
        ).scalars().all()
    }
    events = conn.execute(
        select(Event).where(Event.experiment_id == experiment_id).order_by(Event.id)
    ).scalars().all()

    current: dict[int, tuple[int, int, int, int]] = {}
    prior_times: list[float] = []
    prior_spent: list[float] = []
    replay_views: list[dict[str, Any]] = []
    all_match = True

    for ev in events:
        if ev.kind == "batch":
            obj = versions_by_id[ev.version_id]
            current[obj.batch_no] = (
                obj.group_a_visits, obj.group_a_conv,
                obj.group_b_visits, obj.group_b_conv,
            )
            continue

        obj = views_by_id[ev.view_id]

        na = sum(v[0] for v in current.values())
        xa = sum(v[1] for v in current.values())
        nb = sum(v[2] for v in current.values())
        xb = sum(v[3] for v in current.values())
        t_raw, capped = stats.information_fraction(na, nb, exp.n_per_group)
        t_actual = min(t_raw, 1.0)
        z = (
            stats.z_statistic(na, xa, nb, xb)
            if na > 0 and nb > 0
            else float("nan")
        )
        times, spent, boundary, spent_now = _boundary_path(
            prior_times, prior_spent, t_actual,
            float(exp.alpha), exp.spending_rule,
        )
        t_record = times[-1]  # 与在线一致：落库/重放都使用历史包络
        prior_times.append(t_record)
        prior_spent.append(spent_now)

        replay_view = {
            "info_fraction_raw": t_raw, "info_fraction": t_record,
            "capped": capped, "z_value": z, "spent_at": spent_now,
            "boundary": boundary,
            "crossed": abs(z) >= boundary - 1e-12,
        }
        stored = {
            "info_fraction_raw": float(obj.info_fraction_raw),
            "info_fraction": float(obj.info_fraction_used),
            "capped": obj.capped,
            "z_value": float(obj.z_value),
            "spent_at": float(obj.spent_at),
            "boundary": float(obj.boundary),
            "crossed": obj.crossed,
        }
        match = (
            abs(replay_view["z_value"] - stored["z_value"]) < 1e-9
            and abs(replay_view["boundary"] - stored["boundary"]) < 1e-9
            and abs(replay_view["info_fraction"] - stored["info_fraction"]) < 1e-12
            and replay_view["crossed"] == stored["crossed"]
            and replay_view["capped"] == stored["capped"]
        )
        all_match &= match
        replay_views.append({
            "seq": obj.seq, "match": match,
            "stored": stored, "replay": {
                **replay_view,
                "z_value": None if math.isnan(z) else z,
            },
        })

    n_batches = sum(1 for ev in events if ev.kind == "batch")
    n_views = sum(1 for ev in events if ev.kind == "view")
    return {
        "experiment_id": experiment_id,
        "replayed_batches": n_batches,
        "replayed_views": n_views,
        "all_match": all_match,
        "views": replay_views,
    }
