"""Pydantic 请求/响应模型与字段级校验。"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class FieldError(BaseModel):
    field: str
    message: str


class HTTPError(BaseModel):
    error: str
    fields: list[FieldError] = Field(default_factory=list)
    detail: str | None = None


class ExperimentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    baseline_rate: float
    target_rate: float
    alpha: float
    power: float
    control_label: str = Field(default="control", min_length=1, max_length=100)
    treatment_label: str = Field(default="treatment", min_length=1, max_length=100)

    @field_validator("baseline_rate", "target_rate", "alpha", "power")
    @classmethod
    def _bounded(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("必须是有限数值")
        return v

    @model_validator(mode="after")
    def _check(self) -> "ExperimentCreate":
        errors: list[tuple[str, str]] = []
        if not (0.0 < self.baseline_rate < 1.0):
            errors.append(("baseline_rate", "基线转化率必须在 0 到 1 之间（不含端点）"))
        if not (0.0 < self.target_rate < 1.0):
            errors.append(("target_rate", "目标转化率必须在 0 到 1 之间（不含端点）"))
        if not (0.0 < self.alpha < 1.0):
            errors.append(("alpha", "显著性水平必须在 0 到 1 之间"))
        if not (0.0 < self.power < 1.0):
            errors.append(("power", "功效必须在 0 到 1 之间"))
        if (
            0.0 < self.baseline_rate < 1.0
            and 0.0 < self.target_rate < 1.0
            and self.target_rate == self.baseline_rate
        ):
            errors.append(("target_rate", "目标转化率不能等于基线转化率"))
        if errors:
            raise ValueError(errors)  # 由 app 层转换为字段错误响应
        return self


class ExperimentOut(BaseModel):
    id: int
    name: str
    control_label: str
    treatment_label: str
    baseline_rate: float
    target_rate: float
    alpha: float
    power: float
    min_effect_abs: float
    planned_n_per_group: int
    freeze_past_looks: bool
    concluded: bool
    created_at: datetime

    # 当前累计
    control_visits: int = 0
    control_conversions: int = 0
    treatment_visits: int = 0
    treatment_conversions: int = 0
    current_info_time: float = 0.0
    raw_info_time: float = 0.0
    info_clipped: bool = False
    looks_done: int = 0


class BatchPush(BaseModel):
    batch_no: int = Field(ge=0)
    control_visits: int
    control_conversions: int
    treatment_visits: int
    treatment_conversions: int
    is_correction: bool = False

    @model_validator(mode="after")
    def _check(self) -> "BatchPush":
        errors: list[tuple[str, str]] = []
        for name, v in [
            ("control_visits", self.control_visits),
            ("control_conversions", self.control_conversions),
            ("treatment_visits", self.treatment_visits),
            ("treatment_conversions", self.treatment_conversions),
        ]:
            if v < 0:
                errors.append((name, "必须为非负整数"))
        if self.control_conversions > self.control_visits:
            errors.append(("control_conversions", "转化数不能大于访问数"))
        if self.treatment_conversions > self.treatment_visits:
            errors.append(("treatment_conversions", "转化数不能大于访问数"))
        if errors:
            raise ValueError(errors)
        return self


class BatchOut(BaseModel):
    batch_no: int
    control_visits: int
    control_conversions: int
    treatment_visits: int
    treatment_conversions: int
    correction_count: int
    first_received_at: datetime
    last_updated_at: datetime
    received_seq: int


class BatchEventOut(BaseModel):
    id: int
    batch_no: int
    event_type: str
    control_visits: int
    control_conversions: int
    treatment_visits: int
    treatment_conversions: int
    prior_control_visits: int | None
    prior_control_conversions: int | None
    prior_treatment_visits: int | None
    prior_treatment_conversions: int | None
    note: str | None
    created_at: datetime


class LookOut(BaseModel):
    look_number: int
    trigger: str
    raw_info_time: float
    info_time: float
    clipped: bool
    control_visits: int
    control_conversions: int
    treatment_visits: int
    treatment_conversions: int
    z_stat: float
    boundary: float
    cumulative_spend: float
    decision: str
    correction_since_last: bool
    based_on_event_id: int
    created_at: datetime


class LookTrigger(BaseModel):
    trigger: Literal["manual", "scheduled"] = "manual"


class LookCreateResponse(BaseModel):
    created: bool
    reason: str | None = None
    look: LookOut | None = None
    # 冻结策略提示：哪些历史查看不受本次更正影响
    correction_warning: str | None = None


class ReplayReport(BaseModel):
    experiment_id: int
    events_replayed: int
    looks_replayed: int
    looks: list[LookOut]
    match: bool
    discrepancies: list[str]
    # 重放结束时的累计状态
    control_visits: int
    control_conversions: int
    treatment_visits: int
    treatment_conversions: int


class TrajectoryPoint(BaseModel):
    look_number: int
    info_time: float
    raw_info_time: float
    z_stat: float
    boundary: float
    lower_boundary: float
    decision: str
    trigger: str
    created_at: datetime
    clipped: bool


class TrajectoryOut(BaseModel):
    planned_n_per_group: int
    alpha: float
    freeze_past_looks: bool
    points: list[TrajectoryPoint]
    # 未来边界预览（在计划的等距时点上，仅用于展示消耗形状；不消耗 alpha）
    planned_preview: list[dict]
