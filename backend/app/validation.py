"""入参校验。所有错误聚合成 {字段: 中文原因}，HTTP 422 返回。"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException


class ValidationError(HTTPException):
    def __init__(self, errors: dict[str, str]):
        super().__init__(status_code=422, detail={"errors": errors})


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _num(errors: dict[str, str], field: str, value: Any, name: str) -> float | None:
    if not _is_number(value):
        errors[field] = f"{name}必须是数字"
        return None
    return float(value)


def _int_field(errors: dict[str, str], field: str, value: Any, name: str,
               min_value: int = 0) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        errors[field] = f"{name}必须是整数"
        return None
    if value < min_value:
        errors[field] = f"{name}不能小于{min_value}"
    return value


def validate_experiment_create(payload: dict[str, Any]) -> dict[str, Any]:
    errors: dict[str, str] = {}
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        errors["name"] = "实验名称不能为空"

    baseline = _num(errors, "baseline_rate", payload.get("baseline_rate"), "基线转化率")
    if baseline is not None and not 0.0 < baseline < 1.0:
        errors["baseline_rate"] = "基线转化率必须在 0 到 1 之间（不含端点）"

    target = _num(errors, "target_rate", payload.get("target_rate"), "目标转化率")
    if target is not None and not 0.0 < target < 1.0:
        errors["target_rate"] = "目标转化率必须在 0 到 1 之间（不含端点）"

    alpha = _num(errors, "alpha", payload.get("alpha"), "显著性水平")
    if alpha is not None and not 0.0 < alpha < 1.0:
        errors["alpha"] = "显著性水平必须在 0 到 1 之间（不含端点）"

    power = _num(errors, "power", payload.get("power"), "功效")
    if power is not None and not 0.0 < power < 1.0:
        errors["power"] = "功效必须在 0 到 1 之间（不含端点）"

    spending = payload.get("spending_rule", "obf")
    if spending not in ("obf",):
        errors["spending_rule"] = "当前仅支持 O'Brien-Fleming 消耗规则（obf）"

    if (
        baseline is not None
        and target is not None
        and "target_rate" not in errors
        and "baseline_rate" not in errors
        and abs(target - baseline) < 1e-12
    ):
        errors["target_rate"] = "目标转化率不能等于基线转化率"

    if errors:
        raise ValidationError(errors)
    return {
        "name": name.strip(),
        "baseline_rate": baseline,
        "mde_abs": target - baseline,
        "alpha": alpha,
        "power": power,
        "spending_rule": spending,
    }


def validate_batch_push(payload: dict[str, Any]) -> dict[str, Any]:
    errors: dict[str, str] = {}
    batch_no = _int_field(errors, "batch_no", payload.get("batch_no"), "批次号", min_value=1)

    fields = (
        ("group_a_visits", "A组新增访问数"),
        ("group_a_conv", "A组新增转化数"),
        ("group_b_visits", "B组新增访问数"),
        ("group_b_conv", "B组新增转化数"),
    )
    vals: dict[str, int] = {}
    for key, label in fields:
        vals[key] = _int_field(errors, key, payload.get(key), label)

    note = payload.get("note")
    if note is not None and not isinstance(note, str):
        errors["note"] = "备注必须是字符串"

    if all(v is not None for v in vals.values()):
        av, ac = vals["group_a_visits"], vals["group_a_conv"]
        bv, bc = vals["group_b_visits"], vals["group_b_conv"]
        if ac > av:
            errors["group_a_conv"] = "A组转化数不能大于访问数"
        if bc > bv:
            errors["group_b_conv"] = "B组转化数不能大于访问数"

    if errors:
        raise ValidationError(errors)
    out = {"batch_no": batch_no, **vals}
    if isinstance(note, str) and note.strip():
        out["note"] = note.strip()
    return out
