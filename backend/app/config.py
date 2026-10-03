from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+psycopg2://exp:exp@postgres:5432/experiments"
    )
    auto_look_interval_seconds: float = float(os.getenv("AUTO_LOOK_INTERVAL_SECONDS", "0"))
    # 0 = 关闭自动查看（默认，只有手动触发）；>0 时为后台轮询间隔
    static_dir: str = os.getenv("STATIC_DIR", "/app/static")


settings = Settings()
