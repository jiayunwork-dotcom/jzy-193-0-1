# API 参考

所有请求/响应均为 JSON。校验失败统一返回：

```json
HTTP 422
{"detail": {"errors": {"field_name": "中文原因"}}}
```

## POST /api/experiments — 建实验

请求：

```json
{
  "name": "落地页改版-10月",
  "baseline_rate": 0.10,
  "target_rate": 0.12,
  "alpha": 0.05,
  "power": 0.80,
  "spending_rule": "obf"
}
```

响应 201：

```json
{
  "id": "exp1a2b3c4d5e",
  "name": "落地页改版-10月",
  "baseline_rate": 0.10,
  "target_rate": 0.12,
  "mde_abs": 0.02,
  "alpha": 0.05,
  "power": 0.80,
  "spending_rule": "obf",
  "n_per_group": 3841,
  "status": "running",
  "conclusion": null,
  "concluded_view_seq": null,
  "created_at": "2026-10-03T08:00:00+00:00"
}
```

拒收条件（字段级标注）：转化率不在 (0,1)、目标等于基线、α/功效不在
(0,1)、名称为空、未知消耗规则。

## POST /api/experiments/{id}/batches — 推送批次 / 更正

```json
{
  "batch_no": 12,
  "group_a_visits": 1000, "group_a_conv": 105,
  "group_b_visits": 1000, "group_b_conv": 92,
  "note": "可选备注"
}
```

响应（首次 / 更正 / 幂等忽略三种 action）：

```json
{
  "action": "created | corrected | duplicate_ignored",
  "batch_no": 12,
  "version": 1,
  "message": "批次 12 已更正（第 2 版）。历史查看记录保持冻结……",
  "frozen": false,
  "changed_since_latest_view": true,
  "latest_view_seq": 3,
  "current_totals": {"group_a_visits": 2000, "group_a_conv": 210,
                     "group_b_visits": 2000, "group_b_conv": 190}
}
```

- 同批次号 + 完全相同的四个计数：幂等忽略，不新增版本、不新增事件；
- 同批次号 + 任一计数变化：视为更正，版本 +1，旧值保留在更正流水；
- 拒收：整数字段非整数/为负、转化数大于访问数、实验不存在（字段
  `experiment_id`）。

## POST /api/experiments/{id}/views — 触发查看

```json
{"trigger": "manual"}
```

`trigger` 取 `manual`（默认）或 `scheduled`。响应 201：

```json
{
  "seq": 2,
  "trigger": "manual",
  "total_a_visits": 1920, "total_a_conv": 190,
  "total_b_visits": 1920, "total_b_conv": 220,
  "info_fraction_raw": 0.5,
  "info_fraction": 0.5,
  "capped": false,
  "z_value": -1.5231,
  "spent_before": 0.000089,
  "spent_at": 0.0055746,
  "boundary": 2.7739,
  "crossed": false,
  "conclusion": "inconclusive",
  "warnings": [],
  "experiment_status": "running",
  "experiment_conclusion": null,
  "created_at": "2026-10-03T09:00:00+00:00"
}
```

越界时 `crossed=true`，`conclusion` 为 `a_wins`（z>0）或 `b_wins`
（z<0），实验转为 `stopped` 且结论冻结；之后查看仍会计算并落库，
但 `warnings` 中带冻结提示，实验级结论不再变化。

`info_fraction_raw > 1` 时 `capped=true`，`info_fraction=1`，warnings
中提示「按 1 处理」。累计访问为 0 时返回 409。

## GET /api/experiments/{id}/trajectory — 轨迹

```json
{
  "experiment_id": "...", "status": "running", "conclusion": null,
  "n_per_group": 3841,
  "fixed_boundary": 1.959963984540054,
  "total_alpha": 0.05,
  "points": [ /* 与 GET /views 相同的查看对象数组，按 seq 升序 */ ]
}
```

## GET /api/experiments/{id}/corrections — 推送与更正流水

```json
[
  {"batch_no": 1, "version": 1, "kind": "push",
   "group_a_visits": 1000, "group_a_conv": 105,
   "group_b_visits": 1000, "group_b_conv": 92,
   "note": null, "created_at": "..."},
  {"batch_no": 1, "version": 2, "kind": "correction", "...": "..."}
]
```

## POST /api/experiments/{id}/replay — 从头重放

按全局事件流水重建各查看点数据，独立重算并与在线记录逐项比对：

```json
{
  "experiment_id": "...",
  "replayed_batches": 4,
  "replayed_views": 3,
  "all_match": true,
  "views": [
    {"seq": 1, "match": true,
     "stored": {"z_value": -1.1058, "boundary": 3.8412, "...": "..."},
     "replay": {"z_value": -1.1058, "boundary": 3.8412, "...": "..."}}
  ]
}
```

比对容差：z / 边界 1e-9，信息时间 1e-12，`crossed` 与 `capped` 严格相等。
