"""SQLAlchemy 模型。所有用于重放的状态（实验参数、批次事件、查看快照）都落库，
服务重启后从 PostgreSQL 恢复，重放结果与在线时逐项相同。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    control_label: Mapped[str] = mapped_column(String(100), default="control")
    treatment_label: Mapped[str] = mapped_column(String(100), default="treatment")
    baseline_rate: Mapped[float] = mapped_column(Float, nullable=False)
    target_rate: Mapped[float] = mapped_column(Float, nullable=False)
    alpha: Mapped[float] = mapped_column(Float, nullable=False)
    power: Mapped[float] = mapped_column(Float, nullable=False)
    min_effect_abs: Mapped[float] = mapped_column(Float, nullable=False)
    planned_n_per_group: Mapped[int] = mapped_column(Integer, nullable=False)
    # 冻结策略：已完成查看的边界/消耗永不被后续更正改写
    freeze_past_looks: Mapped[bool] = mapped_column(Boolean, default=True)
    concluded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    batches: Mapped[list["Batch"]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan", order_by="Batch.received_seq"
    )
    events: Mapped[list["BatchEvent"]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan", order_by="BatchEvent.id"
    )
    looks: Mapped[list["Look"]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan", order_by="Look.look_number"
    )


class Batch(Base):
    """每个批次号一行（最新值）。correction_count 记录更正次数。"""

    __tablename__ = "batches"
    __table_args__ = (
        UniqueConstraint("experiment_id", "batch_no", name="uq_batch_experiment_no"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False
    )
    batch_no: Mapped[int] = mapped_column(Integer, nullable=False)
    control_visits: Mapped[int] = mapped_column(Integer, nullable=False)
    control_conversions: Mapped[int] = mapped_column(Integer, nullable=False)
    treatment_visits: Mapped[int] = mapped_column(Integer, nullable=False)
    treatment_conversions: Mapped[int] = mapped_column(Integer, nullable=False)
    correction_count: Mapped[int] = mapped_column(Integer, default=0)
    first_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    # 入库顺序（单调序列），定义重放顺序，与批次号解耦
    received_seq: Mapped[int] = mapped_column(Integer, nullable=False)

    experiment: Mapped[Experiment] = relationship(back_populates="batches")


class BatchEvent(Base):
    """不可变事件流：收到的每次推送（含被忽略的重复与更正），用于审计与确定性重放。"""

    __tablename__ = "batch_events"
    __table_args__ = (Index("ix_events_exp_seq", "experiment_id", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False
    )
    batch_no: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # insert | duplicate_ignored | correction
    control_visits: Mapped[int] = mapped_column(Integer, nullable=False)
    control_conversions: Mapped[int] = mapped_column(Integer, nullable=False)
    treatment_visits: Mapped[int] = mapped_column(Integer, nullable=False)
    treatment_conversions: Mapped[int] = mapped_column(Integer, nullable=False)
    prior_control_visits: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prior_control_conversions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prior_treatment_visits: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prior_treatment_conversions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    experiment: Mapped[Experiment] = relationship(back_populates="events")


class Look(Base):
    """一次查看的冻结快照。数值在创建时算出并持久化，永不修改。"""

    __tablename__ = "looks"
    __table_args__ = (
        UniqueConstraint("experiment_id", "look_number", name="uq_look_experiment_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False
    )
    look_number: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger: Mapped[str] = mapped_column(String(10), nullable=False)  # manual | scheduled
    raw_info_time: Mapped[float] = mapped_column(Float, nullable=False)
    info_time: Mapped[float] = mapped_column(Float, nullable=False)
    clipped: Mapped[bool] = mapped_column(Boolean, default=False)
    control_visits: Mapped[int] = mapped_column(Integer, nullable=False)
    control_conversions: Mapped[int] = mapped_column(Integer, nullable=False)
    treatment_visits: Mapped[int] = mapped_column(Integer, nullable=False)
    treatment_conversions: Mapped[int] = mapped_column(Integer, nullable=False)
    z_stat: Mapped[float] = mapped_column(Float, nullable=False)
    boundary: Mapped[float] = mapped_column(Float, nullable=False)
    cumulative_spend: Mapped[float] = mapped_column(Float, nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    # continue | reject | reject_negative
    prior_info_times_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # 触发查看时基于的最新事件 id（定义「在线时」的状态）
    based_on_event_id: Mapped[int] = mapped_column(Integer, nullable=False)
    # 若触发时存在晚于上一次查看的更正事件，记录用于页面提示
    correction_since_last: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    experiment: Mapped[Experiment] = relationship(back_populates="looks")
