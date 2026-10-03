#!/bin/sh
# 在测试容器内执行：等待 PG → 重建 test_abm → 跑 pytest
set -eu

python - <<'PY'
import time, psycopg2
for _ in range(60):
    try:
        psycopg2.connect("host=db user=abm password=abm dbname=postgres").close()
        break
    except Exception:
        time.sleep(1)
else:
    raise SystemExit("PostgreSQL 未就绪")
PY

python - <<'PY'
import psycopg2
c = psycopg2.connect(
    "host=db user=abm password=abm dbname=postgres", autocommit=True
)
cur = c.cursor()
cur.execute("DROP DATABASE IF EXISTS test_abm")
cur.execute("CREATE DATABASE test_abm")
c.close()
print("test_abm 已就绪")
PY

exec pytest -q /app/tests
