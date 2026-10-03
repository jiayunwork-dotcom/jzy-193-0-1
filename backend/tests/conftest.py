"""pytest 配置。

优先使用 TEST_DATABASE_URL 指向的 PostgreSQL（CI / compose 内运行的口径，
与生产一致）；未设置时回退到内存 SQLite 以便无 PG 的开发机运行逻辑测试。
注意：行级锁（SELECT ... FOR UPDATE）在 SQLite 上为空操作，因此并发相关
行为只在 PostgreSQL 下验证。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app import db as db_module  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402


def _make_engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        eng = create_engine(url, future=True)
        # 清场重建，保证幂等
        Base.metadata.drop_all(eng)
        Base.metadata.create_all(eng)
        return eng, True
    eng = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    return eng, False


@pytest.fixture()
def engine():
    eng, is_pg = _make_engine()
    db_module._engine = eng
    yield eng
    if is_pg:
        Base.metadata.drop_all(eng)
        Base.metadata.create_all(eng)
    eng.dispose()


@pytest.fixture()
def client(engine):
    # 避免 lifespan 再建一次库（已在 fixture 中建好）
    os.environ["CREATE_TABLES"] = "0"
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def session(engine):
    with Session(engine, future=True) as s:
        yield s
