#!/bin/sh
# 生产入口：先跑 Alembic 迁移（可用 WENJING_RUN_MIGRATIONS=0 关闭），再启动服务。
set -e

if [ "${WENJING_RUN_MIGRATIONS:-1}" = "1" ]; then
  echo "[entrypoint] alembic upgrade head ..."
  alembic upgrade head
fi

exec "$@"
