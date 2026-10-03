"""重启恢复：用全新引擎指向同一数据库重放，状态与在线记录一致。

SQLite 文件库场景等价于"进程重启"：全部状态必须来自数据库，不依赖内存。
PG 场景由 docker compose 重启容器覆盖（数据在 pgdata 卷中）。
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import main as webmain
from app import service
from app.models import Experiment


def test_restart_recovers_identical_state(make_experiment, client):
    e = make_experiment()
    eid = e["id"]
    client.post(
        f"/api/experiments/{eid}/batches",
        json={"batch_no": 1, "control_visits": 1000, "control_conversions": 100,
              "treatment_visits": 1000, "treatment_conversions": 130},
    )
    client.post(f"/api/experiments/{eid}/looks")
    client.post(
        f"/api/experiments/{eid}/batches",
        json={"batch_no": 1, "control_visits": 1000, "control_conversions": 95,
              "treatment_visits": 1000, "treatment_conversions": 130,
              "is_correction": True},
    )
    client.post(f"/api/experiments/{eid}/looks")
    online = client.get(f"/api/experiments/{eid}/looks").json()
    assert len(online) == 2

    # 全新引擎/会话指向同一个库文件，模拟服务进程重启
    path = webmain.engine.url.database
    if os.getenv("TEST_DATABASE_URL"):
        restart_engine = create_engine(os.environ["TEST_DATABASE_URL"], future=True)
    else:
        restart_engine = create_engine(
            f"sqlite+pysqlite:///{path}",
            connect_args={"check_same_thread": False},
            future=True,
        )
    Session = sessionmaker(bind=restart_engine, autoflush=False, expire_on_commit=False, future=True)
    db = Session()
    try:
        exp = db.get(Experiment, eid)
        assert exp is not None
        report = service.replay_experiment(db, exp)
        assert report["match"] is True, report["discrepancies"]
        assert report["looks_replayed"] == 2
        # 当前累计已使用更正值
        assert report["totals"].control_conversions == 95
        # 历史第一次查看仍冻结在更正前的值
        assert report["stored_looks"][0].control_conversions == 100
        # 第二行使用更正后的值
        assert report["stored_looks"][1].control_conversions == 95
    finally:
        db.close()
        restart_engine.dispose()
