# A/B 实验监测系统

两组转化率实验的**成组序贯监测**：建实验时固定总显著性水平与计划样本量，
按 O'Brien-Fleming α 消耗规则为每次查看发放停止边界；「天天看、显著就停」
被替换为「越过预算边界才能下结论」。统计口径、边界算法、冻结策略与精度
见 [`docs/stats.md`](docs/stats.md)。

技术栈：FastAPI（Python 3.12）+ PostgreSQL 16 + React 18 / Vite（Node 20
构建），两段式镜像，docker compose 一键启动。

## 快速开始（compose）

```bash
docker compose up --build
# 前端 + API：http://localhost:8000
# PostgreSQL：localhost:5432（abm/abm）
```

表结构在 API 启动时自动创建（`CREATE_TABLES=1`）。

## 本地开发

```bash
# 后端
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r backend/requirements.txt
export DATABASE_URL=postgresql+psycopg2://abm:abm@localhost:5432/abm
uvicorn app.main:app --reload --app-dir backend

# 前端（dev server 自动代理 /api）
cd frontend && npm ci && npm run dev
```

## 测试

```bash
# 方式一：本机直连 PG
export TEST_DATABASE_URL=postgresql+psycopg2://abm:abm@localhost:5432/test_abm
pytest backend/tests

# 方式二：一次性测试容器（自动起 PG 16 并跑全部测试后退出）
./scripts/run_pg_tests.sh
```

未设置 `TEST_DATABASE_URL` 时自动回退内存 SQLite 跑同一套逻辑测试
（行锁语义只在 PostgreSQL 下验证）。

测试覆盖：样本量参考值（3841）、消耗函数参考值（t=0.5→0.00557、
t=1→0.05）、终局单查看边界 1.95996、α 守恒（解析积分 ≤0.05）、多查看
边界单调、z 互换变号、幂等/更正/拒收（全部非法字段场景）、冻结后更正
不改写历史、按事件流水重放逐项一致、重启恢复。

## 页面功能

1. **新建实验**：录入基线/目标转化率、双侧 α、功效，即时得到每组样本量
   （10%→12%、α=0.05、power=0.8 → 3841）。
2. **统计量轨迹**：z 随信息比例推进，叠加每次查看的 ±停止边界（步进折线）
   与 ±1.96 固定样本参考线；查看明细表给出快照、t（原值/截断后）、z、
   已消耗 α、边界、判定；信息比例超 1 有显著标注。
3. **批次明细 / 推送与更正流水**：当前生效批次 + 不可变审计流水；
   推送表单同号幂等、异号即更正，更正后页面提示冻结影响。
4. **手动触发一次查看**：后端完成全部计算；越过边界立即给出 A 胜/B 胜
   结论与当时统计量，实验级结论冻结。
5. **从头重放校验**：按全局事件顺序重算全部查看并与在线记录逐项比对。

## 核心约定（务必先读）

- **冻结**：已发生查看的边界、已消耗 α、结论永不被更正改写；更正只影响
  后续查看。代价见 `docs/stats.md` 第 5 节。
- **α 账本**：累计消耗单调不减、不超过总 α；信息时间取历史非递减包络，
  更正减量不会让 α「倒流」。
- **确定可重复**：边界用固定格点确定性 Simpson 积分 + 二分，无随机数；
  重放以全局自增事件序号排序（不依赖时间戳）。

## API 摘要

详见 [`docs/api.md`](docs/api.md)。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/experiments` | 建实验，返回每组样本量 |
| GET | `/api/experiments` | 实验列表 |
| GET | `/api/experiments/{id}` | 实验详情 |
| POST | `/api/experiments/{id}/batches` | 推送批次（幂等/更正） |
| GET | `/api/experiments/{id}/batches` | 当前生效批次 |
| GET | `/api/experiments/{id}/corrections` | 推送/更正流水 |
| POST | `/api/experiments/{id}/views` | 触发一次查看（手动/定时） |
| GET | `/api/experiments/{id}/views` | 查看历史 |
| GET | `/api/experiments/{id}/trajectory` | 轨迹 + 边界点 |
| POST | `/api/experiments/{id}/replay` | 从头重放并比对 |

非法输入统一 HTTP 422：`{"detail": {"errors": {"字段": "原因"}}}`。
