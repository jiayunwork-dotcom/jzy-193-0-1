# HTTP 接口

错误响应统一结构：

```json
{ "error": "validation_failed|conflict|not_found",
  "detail": "人类可读说明",
  "fields": [{"field": "target_rate", "message": "目标转化率不能等于基线转化率"}] }
```

状态码：200/201 成功；404 实验不存在；409 状态冲突（重复查看、未声明更正、
无样本等）；422 字段校验失败（字段级标注）。

## 实验

### POST /api/experiments
请求：`name, baseline_rate, target_rate, alpha, power, control_label?, treatment_label?`
```json
{ "name": "落地页改版", "baseline_rate": 0.10, "target_rate": 0.12,
  "alpha": 0.05, "power": 0.8 }
```
201：完整实验对象，含 `planned_n_per_group=3841`、`freeze_past_looks=true`
及当前累计（初始全 0）。

422 字段：`baseline_rate`/`target_rate`（必须严格在 (0,1)，且不相等）、
`alpha`/`power`（必须严格在 (0,1)）。

### GET /api/experiments · GET /api/experiments/{id}
返回实验列表/详情，含累计访问、转化、当前（截断后）信息比例、
`raw_info_time`、`info_clipped`、查看次数、`concluded`。

## 批次

### POST /api/experiments/{id}/batches
```json
{ "batch_no": 12,
  "control_visits": 1000, "control_conversions": 100,
  "treatment_visits": 1000, "treatment_conversions": 120,
  "is_correction": false }
```
- 新批次：`status="insert"`；
- 同批次号同内容重发：200 `status="duplicate_ignored"`（幂等）；
- 同批次号不同内容且 `is_correction=false`：409，字段
  `batch_no`+`is_correction`；
- `is_correction=true`：`status="correction"`，覆盖旧值、`correction_count+1`，
  事件流保留前后值；对不存在批次发更正：409。

422 字段：任一字段为负、转化数大于访问数（按组分别标出）。
404：实验不存在。

### GET /api/experiments/{id}/batches
每个批次号一行最新值（含 `correction_count`、`received_seq`）。

### GET /api/experiments/{id}/events
不可变事件流（按接收顺序）：`insert|correction|duplicate_ignored`，
更正事件含 prior_* 旧值与备注。

## 查看

### POST /api/experiments/{id}/looks
请求体可选 `{"trigger":"manual"}`（默认 manual；调度器用 scheduled）。
200：
```json
{ "created": true,
  "look": {
    "look_number": 3, "trigger": "manual",
    "raw_info_time": 0.512, "info_time": 0.512, "clipped": false,
    "control_visits": 3000, "control_conversions": 300,
    "treatment_visits": 3000, "treatment_conversions": 360,
    "z_stat": 2.49, "boundary": 2.63,
    "cumulative_spend": 0.0062,
    "decision": "continue|reject|reject_negative",
    "correction_since_last": false,
    "based_on_event_id": 17,
    "created_at": "..." },
  "correction_warning": null }
```
409：两组累计访问为 0；或自上次查看无新事件（同状态重复查看）。
下过结论后有更正/新事件时仍可查看；若更正后 Z 回到界内，
`correction_warning` 给出"当前证据不再支持历史结论"提示（历史行不改写）。

### GET /api/experiments/{id}/looks
全部冻结查看快照，按查看号升序。

### GET /api/experiments/{id}/trajectory
```json
{ "planned_n_per_group": 3841, "alpha": 0.05, "freeze_past_looks": true,
  "points": [ {实际查看点：t, z_stat, boundary, lower_boundary, decision,…} ],
  "planned_preview": [ {info_time:0.1..1.0, boundary, lower_boundary,
                        cumulative_spend} ] }
```
`planned_preview` 仅用于画计划消耗形状（10 个等距点），不产生实际查看。

### POST /api/experiments/{id}/replay
按不可变事件流从头重建并重算全部历史查看，逐字段比对在线快照：
```json
{ "events_replayed": 5, "looks_replayed": 4, "match": true,
  "discrepancies": [], "looks": [...], "control_visits": …, … }
```
正常应为 `match=true`；任何不一致会列出「第 k 次查看字段 X：重放 … != 在线 …」。

## 运维

### GET /api/health
数据库连通时 `{"status":"ok"}`，否则 503。
