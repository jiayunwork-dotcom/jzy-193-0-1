"""数据库引擎与会话（SQLAlchemy Core 2.x，PostgreSQL）。

状态全部落库，进程内不保留任何可变状态：重启即从 PostgreSQL 恢复，
天然满足「服务重启后恢复出相同状态」。
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://abm:abm@localhost:5432/abm",
)

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(
            DATABASE_URL,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            future=True,
        )
    return _engine
