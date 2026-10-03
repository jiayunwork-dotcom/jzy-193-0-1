"""表结构（PostgreSQL 16）。

experiments        实验建跑时录入的设计参数（冻结）
batches            每批次的「当前生效」数据（同号幂等；更正原地更新）
batch_versions     每次推送/更正的不可变流水（审计 + 重放）
views              每次查看的快照、边界、结论（冻结，见 docs/stats.md）
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    baseline_rate: Mapped[float] = mapped_column(Numeric(12, 8), nullable=False)
    mde_abs: Mapped[float] = mapped_column(Numeric(12, 8), nullable=False)
    alpha: Mapped[float] = mapped_column(Numeric(8, 6), nullable=False)
    power: Mapped[float] = mapped_column(Numeric(8, 6), nullable=False)
    spending_rule: Mapped[str] = mapped_column(String(20), nullable=False, default="obf")
    n_per_group: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    # stopped = 已越过边界下过结论；running = 监测中
    conclusion: Mapped[str | None] = mapped_column(String(20), nullable=True)
    concluded_view_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Batch(Base):
    __tablename__ = "batches"
    __table_args__ = (
        UniqueConstraint("experiment_id", "batch_no", name="uq_batch"),
        CheckConstraint("group_a_visits >= 0", name="ck_batch_a_visits"),
        CheckConstraint("group_b_visits >= 0", name="ck_batch_b_visits"),
        CheckConstraint("group_a_conv >= 0", name="ck_batch_a_conv"),
        CheckConstraint("group_b_conv >= 0", name="ck_batch_b_conv"),
        CheckConstraint("group_a_conv <= group_a_visits", name="ck_batch_a_rate"),
        CheckConstraint("group_b_conv <= group_b_visits", name="ck_batch_b_rate"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False
    )
    batch_no: Mapped[int] = mapped_column(Integer, nullable=False)
    group_a_visits: Mapped[int] = mapped_column(Integer, nullable=False)
    group_a_conv: Mapped[int] = mapped_column(Integer, nullable=False)
    group_b_visits: Mapped[int] = mapped_column(Integer, nullable=False)
    group_b_conv: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BatchVersion(Base):
    __tablename__ = "batch_versions"
    __table_args__ = (
        Index("ix_versions_exp_batch_version", "experiment_id", "batch_no", "version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False
    )
    batch_no: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # push | correction
    group_a_visits: Mapped[int] = mapped_column(Integer, nullable=False)
    group_a_conv: Mapped[int] = mapped_column(Integer, nullable=False)
    group_b_visits: Mapped[int] = mapped_column(Integer, nullable=False)
    group_b_conv: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Event(Base):
    """全局事件流水：批次推送/更正与查看共用一个自增序号。

    重放必须与在线顺序逐项一致，不能依赖时间戳（同事务/同微秒会打平），
    因此所有状态变更在同一事务内追加一行，按 id 排序即真实发生顺序。
    """

    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_exp", "experiment_id", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # batch | view
    version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    view_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class View(Base):
    __tablename__ = "views"
    __table_args__ = (
        UniqueConstraint("experiment_id", "seq", name="uq_view_seq"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger: Mapped[str] = mapped_column(String(10), nullable=False)  # manual | scheduled
    # 快照：本次查看时所有生效批次的累计值（冻结）
    total_a_visits: Mapped[int] = mapped_column(Integer, nullable=False)
    total_a_conv: Mapped[int] = mapped_column(Integer, nullable=False)
    total_b_visits: Mapped[int] = mapped_column(Integer, nullable=False)
    total_b_conv: Mapped[int] = mapped_column(Integer, nullable=False)
    info_fraction_raw: Mapped[float] = mapped_column(Numeric(18, 15), nullable=False)
    info_fraction_used: Mapped[float] = mapped_column(Numeric(18, 15), nullable=False)
    capped: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    z_value: Mapped[float] = mapped_column(Numeric(20, 15), nullable=False)
    spent_before: Mapped[float] = mapped_column(Numeric(20, 15), nullable=False)
    spent_at: Mapped[float] = mapped_column(Numeric(20, 15), nullable=False)
    boundary: Mapped[float] = mapped_column(Numeric(20, 15), nullable=False)
    crossed: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    conclusion: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
