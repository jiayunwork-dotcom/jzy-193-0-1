# 成组序贯实验监测系统

两组转化率 A/B 实验的在线监测：建实验时锁定总显著性水平 α、功效与每组计划
样本量；批次数据增量推送（幂等 + 显式更正）；每次查看按当前信息比例与
**Lan-DeMets O'Brien-Fleming α 消耗函数**计算当次停止边界，完整计入多次查看
之间的相关性；历史查看的边界与结论**冻结**，更正只影响后续查看。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | FastAPI · Python 3.12 · SQLAlchemy 2 · SciPy/NumPy（仅正态函数；边界为自研确定性递推） |
| 数据库 | PostgreSQL 16（批次表 + 不可变事件流 + 冻结查看快照） |
| 前端 | React 18 · Vite 5 · Recharts |
| 镜像 | 两段式：`node:20-alpine` 构建 → `python:3.12-slim` 托管 API + 静态页面 |
| 测试 | pytest（统计数值单测 + API 集成测试，40 用例） |

## 快速开始

```bash
docker compose up --build
# API & 页面： http://localhost:8000
# PostgreSQL： localhost:5432 (exp/exp/experiments)
```

健康检查：`GET http://localhost:8000/api/health`。
自动定时查看默认关闭（`AUTO_LOOK_INTERVAL_SECONDS=0`，只支持手动）；
设为正数（如 3600）可开启后台轮询。

本地开发：

```bash
# 后端
cd backend && pip install -r requirements.txt
DATABASE_URL=postgresql+psycopg2://exp:exp@localhost:5432/experiments \
  uvicorn app.main:app --reload

# 前端（dev server 代理 /api 到 8000）
cd frontend && npm install && npm run dev
```

## 测试

```bash
cd backend
# 有 PostgreSQL（推荐，与生产一致）
TEST_DATABASE_URL=postgresql+psycopg2://exp:exp@localhost:5432/experiments \
  pytest -q
# 本地无 PG 时自动回退到 SQLite（应用只使用通用 SQLAlchemy 类型）
pytest -q
```

关键不变量均有测试守护：

- `test_create_experiment_returns_3841`：参考口径每组 3841；
- `test_alpha_spend_reference_values`：t=0.5 时 0.0055746、t=1 恰好 0.05、单调不减；
- `test_boundary_single_look_at_one`：只在 t=1 查看一次边界 == 1.95996398；
- `test_swap_groups_flips_z_and_decision`：两组互换 Z 变号、结论对称；
- `test_replay_matches_online_pointwise` / `..._deterministic_across_calls`：
  按批次重放与在线逐项相同、多次重放结果一致；
- 校验拒收：转化率越界、目标=基线、α/功效越界、转化>访问或为负、
  推给不存在实验，均返回 422/404/409 并带字段名。

## 文档

- [`docs/statistics.md`](docs/statistics.md) — 样本量/Z/信息比例/α 消耗/边界递推的
  完整口径与数值精度（含与教科书边界表的对照）；
- [`docs/design.md`](docs/design.md) — **冻结 vs 不冻结**的决策、代价、更正提示、
  幂等规则、重启恢复与重放；
- [`docs/api.md`](docs/api.md) — HTTP 接口一览。

## 典型流程

1. `POST /api/experiments` 录入基线 10%、目标 12%、α=0.05、功效 0.8
   → 返回 `planned_n_per_group=3841`。
2. 埋点平台每来一批：`POST /api/experiments/{id}/batches`（带批次号）。
   重发安全（幂等），改数必须显式 `is_correction=true`。
3. 想看才看：`POST /api/experiments/{id}/looks`。返回当次 t、Z、±边界、
   累计消耗、结论；|Z|>边界即给出方向（实验更优/对照更优）。
4. 轨迹页查看 Z 沿信息比例的推进，叠加计划边界与每次实际（冻结）边界；
   批次页与事件页核对更正；随时可点「按批次重放」做确定性自检。
