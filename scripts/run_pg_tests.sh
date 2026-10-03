#!/usr/bin/env bash
# 对真实 PostgreSQL 16 运行后端 pytest（一次性容器，跑完即退出）。
# 用法：docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm tests
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm tests
