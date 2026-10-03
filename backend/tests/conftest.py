"""pytest 配置。

优先使用 PostgreSQL（docker/CI 通过 TEST_DATABASE_URL 指向 postgres:16）；
本地无 PG 时回退 SQLite 文件库。应用层只使用通用 SQLAlchemy 类型，
统计内核与业务逻辑在两个后端上一致。每个用例独立建表/删表以保证隔离。
"""

from __future__ import annotations

import os
import sys
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AUTO_LOOK_INTERVAL_SECONDS", "0")

from app import main as webmain  # noqa: E402
from app.models import Base  # noqa: E402

DB_URL = os.getenv("TEST_DATABASE_URL")


def _new_engine():
    if DB_URL:
        return create_engine(DB_URL, future=True)
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return create_engine(
        f"sqlite+pysqlite:///{path}",
        connect_args={"check_same_thread": False},
        future=True,
    ), path


@pytest.fixture()
def db():
    if DB_URL:
        eng = create_engine(DB_URL, future=True)
    else:
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        eng = create_engine(
            f"sqlite+pysqlite:///{path}",
            connect_args={"check_same_thread": False},
            future=True,
        )
    Base.metadata.drop_all(bind=eng)
    Base.metadata.create_all(bind=eng)
    TestingSession = sessionmaker(
        bind=eng, autoflush=False, expire_on_commit=False, future=True
    )
    webmain.engine = eng  # health 检查等使用
    original = webmain.SessionLocal
    webmain.SessionLocal = TestingSession
    session = TestingSession()
    yield session
    session.close()
    webmain.SessionLocal = original
    Base.metadata.drop_all(bind=eng)
    eng.dispose()
    if not DB_URL:
        os.unlink(path)


@pytest.fixture()
def client(db):
    def _get_db_override():
        # 每个请求开新 session（同一引擎/文件），确保 commit 可见
        s = webmain.SessionLocal()
        try:
            yield s
        finally:
            s.close()

    webmain.app.dependency_overrides[webmain.get_db] = _get_db_override
    with TestClient(webmain.app) as c:
        yield c
    webmain.app.dependency_overrides.clear()


@pytest.fixture()
def make_experiment(client):
    def _make(**overrides):
        body = {
            "name": "示例实验",
            "baseline_rate": 0.10,
            "target_rate": 0.12,
            "alpha": 0.05,
            "power": 0.8,
        }
        body.update(overrides)
        r = client.post("/api/experiments", json=body)
        assert r.status_code == 201, r.text
        return r.json()

    return _make
