"""核心业务逻辑：批次幂等/更正、累计状态、冻结式查看与确定性重放。"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import stats
from .models import Batch, BatchEvent, Experiment, Look


class NotFoundError(Exception):
    pass


class ConflictError(Exception):
    def __init__(self, message: str, fields: list[tuple[str, str]] | None = None):
        super().__init__(message)
        self.fields = fields or []


@dataclass
class Totals:
    control_visits: int = 0
    control_conversions: int = 0
    treatment_visits: int = 0
    treatment_conversions: int = 0


# ------------------------------ 批次操作 ----------------------------------- #


def _next_received_seq(db: Session, experiment_id: int) -> int:
    current = db.scalar(
        select(func.coalesce(func.max(Batch.received_seq), 0)).where(
            Batch.experiment_id == experiment_id
        )
    )
    return int(current) + 1


def push_batch(db: Session, experiment: Experiment, payload) -> dict:
    """推送一批。返回 {status, batch, event}。

    - 同批次号、同内容重复推送：幂等忽略，只追加 duplicate_ignored 事件
    - 同批次号、不同内容、is_correction=False：拒绝（409，要求显式更正）
    - is_correction=True：覆盖批次值，correction_count+1，追加 correction 事件
    """
    existing = db.scalar(
        select(Batch)
        .where(Batch.experiment_id == experiment.id, Batch.batch_no == payload.batch_no)
        .with_for_update()
    )
    new_vals = (
        payload.control_visits,
        payload.control_conversions,
        payload.treatment_visits,
        payload.treatment_conversions,
    )
    if existing is not None:
        old_vals = (
            existing.control_visits,
            existing.control_conversions,
            existing.treatment_visits,
            existing.treatment_conversions,
        )
        if old_vals == new_vals:
            event = BatchEvent(
                experiment_id=experiment.id,
                batch_no=payload.batch_no,
                event_type="duplicate_ignored",
                control_visits=new_vals[0],
                control_conversions=new_vals[1],
                treatment_visits=new_vals[2],
                treatment_conversions=new_vals[3],
                prior_control_visits=old_vals[0],
                prior_control_conversions=old_vals[1],
                prior_treatment_visits=old_vals[2],
                prior_treatment_conversions=old_vals[3],
                note="同批次号同内容重复推送，已按幂等规则忽略",
            )
            db.add(event)
            db.flush()
            return {"status": "duplicate_ignored", "batch": existing, "event": event}

        if not payload.is_correction:
            raise ConflictError(
                f"批次号 {payload.batch_no} 已推送过且内容不同；如为更正请显式置 is_correction=true",
                fields=[
                    ("batch_no", "该批次号已存在不同内容"),
                    ("is_correction", "更正已有批次必须置 is_correction=true"),
                ],
            )

        event = BatchEvent(
            experiment_id=experiment.id,
            batch_no=payload.batch_no,
            event_type="correction",
            control_visits=new_vals[0],
            control_conversions=new_vals[1],
            treatment_visits=new_vals[2],
            treatment_conversions=new_vals[3],
            prior_control_visits=old_vals[0],
            prior_control_conversions=old_vals[1],
            prior_treatment_visits=old_vals[2],
            prior_treatment_conversions=old_vals[3],
            note="更正：已覆盖该批次旧值（历史查看的边界与结论保持冻结）",
        )
        existing.control_visits = new_vals[0]
        existing.control_conversions = new_vals[1]
        existing.treatment_visits = new_vals[2]
        existing.treatment_conversions = new_vals[3]
        existing.correction_count += 1
        db.add(event)
        db.flush()
        return {"status": "correction", "batch": existing, "event": event}

    if payload.is_correction:
        raise ConflictError(
            f"批次号 {payload.batch_no} 不存在，无法更正",
            fields=[("batch_no", "不能对不存在的批次发更正")],
        )

    seq = _next_received_seq(db, experiment.id)
    batch = Batch(
        experiment_id=experiment.id,
        batch_no=payload.batch_no,
        control_visits=new_vals[0],
        control_conversions=new_vals[1],
        treatment_visits=new_vals[2],
        treatment_conversions=new_vals[3],
        correction_count=0,
        received_seq=seq,
    )
    event = BatchEvent(
        experiment_id=experiment.id,
        batch_no=payload.batch_no,
        event_type="insert",
        control_visits=new_vals[0],
        control_conversions=new_vals[1],
        treatment_visits=new_vals[2],
        treatment_conversions=new_vals[3],
    )
    db.add(batch)
    db.add(event)
    db.flush()
    return {"status": "insert", "batch": batch, "event": event}


def current_totals(db: Session, experiment_id: int) -> Totals:
    """以 received_seq 定义的「当前批次表」求和。"""
    rows = db.scalars(select(Batch).where(Batch.experiment_id == experiment_id)).all()
    t = Totals()
    for b in rows:
        t.control_visits += b.control_visits
        t.control_conversions += b.control_conversions
        t.treatment_visits += b.treatment_visits
        t.treatment_conversions += b.treatment_conversions
    return t


def latest_event_id(db: Session, experiment_id: int) -> int:
    val = db.scalar(
        select(func.coalesce(func.max(BatchEvent.id), 0)).where(
            BatchEvent.experiment_id == experiment_id
        )
    )
    return int(val)


# ------------------------------ 查看逻辑 ----------------------------------- #


def _freeze_note(last_look: Look | None, db: Session, experiment_id: int) -> tuple[bool, str | None]:
    """自上次查看后是否发生过影响当前累计值的更正事件。"""
    q = select(BatchEvent).where(
        BatchEvent.experiment_id == experiment_id,
        BatchEvent.event_type == "correction",
    )
    if last_look is not None:
        q = q.where(BatchEvent.id > last_look.based_on_event_id)
    correction = db.scalars(q.order_by(BatchEvent.id)).first()
    if correction is None:
        return False, None
    msg = (
        f"检测到批次 {correction.batch_no} 的更正。按冻结策略：历史查看（边界、"
        f"Z 与结论）不被改写；更正只进入本次及以后的查看。当前累计值已使用新值，"
        f"请关注轨迹在信息时间轴上的跳变。"
    )
    return True, msg


def perform_look(db: Session, experiment: Experiment, trigger: str, force: bool = False) -> dict:
    """执行一次查看。冻结策略下，本次边界仅由历史查看的（已冻结）时点序列决定。

    拒绝条件：
      - 无累计样本
      - 与上次查看基于同一事件（同状态重复查看）
    已下结论的实验在收到更正/新数据后仍可继续查看（历史结论冻结，
    新查看若不再越界会给出明确的"证据反转"提示）。
    """
    looks = list(db.scalars(
        select(Look)
        .where(Look.experiment_id == experiment.id)
        .order_by(Look.look_number)
    ))
    last = looks[-1] if looks else None
    # 串行化同一实验的并发查看（手动与定时同时触发）：PG 下锁实验行到提交，
    # 保证 based_on_event_id 去重检查不被并发绕过；SQLite 为库级写锁，无需此步。
    locked_q = select(Experiment).where(Experiment.id == experiment.id)
    if db.get_bind().dialect.name == "postgresql":
        locked_q = locked_q.with_for_update()
    locked = db.scalar(locked_q)
    was_concluded = bool(locked.concluded)

    totals = current_totals(db, experiment.id)
    if totals.control_visits <= 0 or totals.treatment_visits <= 0:
        raise ConflictError("两组都还没有样本，无法查看", fields=[
            ("control_visits", "对照组累计访问数为 0"),
            ("treatment_visits", "实验组累计访问数为 0"),
        ])

    event_id = latest_event_id(db, experiment.id)
    if last is not None and last.based_on_event_id == event_id and not force:
        raise ConflictError(
            "自上次查看以来没有新的批次事件（同一状态重复查看不产生新的边界点）",
            fields=[],
        )
    # 冻结策略下：一旦越界下结论，concluded 不再改写；但更正后仍允许继续查看，
    # 新查看若不再越界，会在页面上明确提示「更正后证据不再支持原结论」。

    # 信息时间单调化：更正可能使原始 t 倒退；在冻结策略下将本次有效 t 夹在
    # [上次有效 t, 1]，并记录 clipped/t_regress 提示
    eff_t, raw_t, clipped_over = stats.info_time(
        totals.control_visits, totals.treatment_visits, experiment.planned_n_per_group
    )
    regressed = False
    if last is not None and eff_t < last.info_time:
        eff_t = last.info_time
        regressed = True

    z = stats.z_statistic(
        totals.control_conversions,
        totals.control_visits,
        totals.treatment_conversions,
        totals.treatment_visits,
    )
    past_ts = [lk.info_time for lk in looks]
    result = stats.evaluate_look(
        look_number=len(looks) + 1,
        past_info_times=past_ts,
        effective_t=eff_t,
        raw_t=raw_t,
        clipped=clipped_over or regressed,
        z=z,
        alpha=experiment.alpha,
    )

    correction_flag, correction_msg = _freeze_note(last, db, experiment.id)
    note = correction_msg
    if regressed:
        extra = (
            "更正使原始信息比例倒退（raw=%.6f），已按单调不减规则夹到上次值 %.6f。"
            % (raw_t, last.info_time)
        )
        note = (note + " " + extra) if note else extra
    if was_concluded and result.decision == "continue" and last is not None and last.decision != "continue":
        extra = (
            "注意：实验曾在第 %d 次查看越过边界并宣布结论；更正后的当前统计量 "
            "Z=%.4f 未越过本次边界 %.4f。历史结论按冻结策略保留不改写，但当前证据"
            "已不再支持该结论，请在发布决策中谨慎处理。" % (last.look_number, result.z, result.boundary)
        )
        note = (note + " " + extra) if note else extra

    look = Look(
        experiment_id=experiment.id,
        look_number=len(looks) + 1,
        trigger=trigger,
        raw_info_time=raw_t,
        info_time=result.info_time,
        clipped=result.clipped,
        control_visits=totals.control_visits,
        control_conversions=totals.control_conversions,
        treatment_visits=totals.treatment_visits,
        treatment_conversions=totals.treatment_conversions,
        z_stat=result.z,
        boundary=result.boundary,
        cumulative_spend=result.cumulative_spend,
        decision=result.decision,
        prior_info_times_json=json.dumps(past_ts),
        based_on_event_id=event_id,
        correction_since_last=correction_flag,
    )
    db.add(look)
    if result.decision != "continue":
        experiment.concluded = True
    db.flush()
    return {"look": look, "warning": note}


# ------------------------------ 重放 -------------------------------------- #


def replay_experiment(db: Session, experiment: Experiment) -> dict:
    """按事件流（BatchEvent.id 顺序）从头重放：

    1. 从事件流重建批次表（insert/correction 生效，duplicate_ignored 无副作用）
    2. 在每次历史查看「触发时对应的事件 id」处截断，使用与在线相同的
       冻结式查看计算，逐点比对持久化的边界/结论/Z/信息时间
    3. 继续重放剩余事件得到最终累计状态
    """
    events = list(db.scalars(
        select(BatchEvent)
        .where(BatchEvent.experiment_id == experiment.id)
        .order_by(BatchEvent.id)
    ))
    stored_looks = list(db.scalars(
        select(Look)
        .where(Look.experiment_id == experiment.id)
        .order_by(Look.look_number)
    ))

    # 用普通 dict 做内存批次表
    mem_batches: dict[int, tuple[int, int, int, int]] = {}

    def totals_at() -> Totals:
        t = Totals()
        for cv, cc, tv, tc in mem_batches.values():
            t.control_visits += cv
            t.control_conversions += cc
            t.treatment_visits += tv
            t.treatment_conversions += tc
        return t

    discrepancies: list[str] = []
    replay_rows: list[Look] = []  # 内存中的对比结果（不落库）
    look_by_event = {lk.based_on_event_id: lk for lk in stored_looks}
    past_ts: list[float] = []
    concluded = False
    n_looks = 0

    for ev in events:
        vals = (
            ev.control_visits,
            ev.control_conversions,
            ev.treatment_visits,
            ev.treatment_conversions,
        )
        if ev.event_type == "insert":
            mem_batches[ev.batch_no] = vals
        elif ev.event_type == "correction":
            mem_batches[ev.batch_no] = vals
        elif ev.event_type == "duplicate_ignored":
            # 幂等：内容必然相同，无副作用
            if mem_batches.get(ev.batch_no) != vals and ev.batch_no in mem_batches:
                discrepancies.append(
                    f"事件 {ev.id}: duplicate_ignored 与当前批次值不一致"
                )
        else:
            discrepancies.append(f"事件 {ev.id}: 未知事件类型 {ev.event_type}")

        if ev.id in look_by_event:
            stored = look_by_event[ev.id]
            totals = totals_at()
            eff_t, raw_t, clip_over = stats.info_time(
                totals.control_visits,
                totals.treatment_visits,
                experiment.planned_n_per_group,
            )
            regressed = False
            if replay_rows:
                prev_eff = replay_rows[-1].info_time
                if eff_t < prev_eff:
                    eff_t = prev_eff
                    regressed = True
            z = stats.z_statistic(
                totals.control_conversions,
                totals.control_visits,
                totals.treatment_conversions,
                totals.treatment_visits,
            )
            res = stats.evaluate_look(
                look_number=n_looks + 1,
                past_info_times=past_ts,
                effective_t=eff_t,
                raw_t=raw_t,
                clipped=clip_over or regressed,
                z=z,
                alpha=experiment.alpha,
            )
            past_ts.append(res.info_time)
            # 构造一个轻量对象便于复用输出
            replay_look = _MemoryLook(
                look_number=stored.look_number,
                trigger=stored.trigger,
                raw_info_time=res.raw_info_time,
                info_time=res.info_time,
                clipped=res.clipped,
                control_visits=totals.control_visits,
                control_conversions=totals.control_conversions,
                treatment_visits=totals.treatment_visits,
                treatment_conversions=totals.treatment_conversions,
                z_stat=res.z,
                boundary=res.boundary,
                cumulative_spend=res.cumulative_spend,
                decision=res.decision,
                correction_since_last=stored.correction_since_last,
                based_on_event_id=ev.id,
                created_at=stored.created_at,
            )
            replay_rows.append(replay_look)
            n_looks += 1
            if res.decision != "continue":
                concluded = True
            # 逐项比较（容差见 docs/design.md 的数值精度一节）
            tol_b, tol_z = 1e-9, 1e-9
            checks = [
                ("info_time", res.info_time, stored.info_time, 1e-12),
                ("raw_info_time", res.raw_info_time, stored.raw_info_time, 1e-12),
                ("boundary", res.boundary, stored.boundary, tol_b),
                ("z_stat", res.z, stored.z_stat, tol_z),
                ("cumulative_spend", res.cumulative_spend, stored.cumulative_spend, 1e-12),
                ("control_visits", totals.control_visits, stored.control_visits, 0),
                ("treatment_visits", totals.treatment_visits, stored.treatment_visits, 0),
                ("control_conversions", totals.control_conversions, stored.control_conversions, 0),
                ("treatment_conversions", totals.treatment_conversions, stored.treatment_conversions, 0),
            ]
            if bool(res.clipped) != bool(stored.clipped):
                discrepancies.append(
                    f"第 {stored.look_number} 次查看 clipped 标志: 重放 {bool(res.clipped)} "
                    f"!= 在线 {bool(stored.clipped)}"
                )
            for name, a, b2, tol in checks:
                if abs(a - b2) > tol:
                    discrepancies.append(
                        f"第 {stored.look_number} 次查看字段 {name}: 重放 {a!r} != 在线 {b2!r}"
                    )
            if res.decision != stored.decision:
                discrepancies.append(
                    f"第 {stored.look_number} 次查看结论: 重放 {res.decision} != 在线 {stored.decision}"
                )

    if n_looks != len(stored_looks):
        discrepancies.append(
            f"查看次数不一致: 重放 {n_looks} != 在线 {len(stored_looks)}"
        )

    final_totals = totals_at()
    return {
        "events_replayed": len(events),
        "looks_replayed": n_looks,
        "looks": replay_rows,
        "stored_looks": stored_looks,
        "match": len(discrepancies) == 0 and n_looks == len(stored_looks),
        "discrepancies": discrepancies,
        "totals": final_totals,
        "concluded": concluded,
    }


class _MemoryLook:
    def __init__(self, **kw):
        self.__dict__.update(kw)
