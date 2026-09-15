#!/usr/bin/env bash
# 文境本地启动脚本：PostgreSQL(可选) + backend(FastAPI) + frontend(Next.js)
#
# 用法：
#   ./scripts/dev.sh [start|stop|restart|status|logs]
#
# 可用环境变量覆盖：
#   BACKEND_HOST/BACKEND_PORT (默认 127.0.0.1:8000)
#   FRONTEND_HOST/FRONTEND_PORT (默认 127.0.0.1:3000)
#   START_DB=0           不尝试启动 docker compose 的 db
#   WENJING_LLM_API_KEY  透传给后端（留空则用确定性 fake）
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT/backend"
FRONTEND_DIR="$ROOT/frontend"
RUN_DIR="$ROOT/.run"
LOG_DIR="$RUN_DIR/logs"

BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
START_DB="${START_DB:-1}"

BACKEND_URL="http://${BACKEND_HOST}:${BACKEND_PORT}"
FRONTEND_URL="http://${FRONTEND_HOST}:${FRONTEND_PORT}"

mkdir -p "$LOG_DIR"

c_info='\033[36m'; c_warn='\033[33m'; c_err='\033[31m'; c_off='\033[0m'
log()  { printf "${c_info}[dev]${c_off} %s\n" "$*"; }
warn() { printf "${c_warn}[dev]${c_off} %s\n" "$*"; }
die()  { printf "${c_err}[dev]${c_off} %s\n" "$*" >&2; exit 1; }

up() { curl --max-time 2 -fsS "$1" >/dev/null 2>&1; }
pid_file() { echo "$RUN_DIR/$1.pid"; }

# 在独立进程组(会话)中启动命令，pid 文件记录组长 pid，便于整组回收
spawn() { # <name> <workdir> <logfile> <cmd...>
  local name="$1" dir="$2" logf="$3"; shift 3
  (
    cd "$dir" || exit 1
    if command -v setsid >/dev/null 2>&1; then
      setsid "$@" </dev/null >"$logf" 2>&1 &
    else
      nohup "$@" </dev/null >"$logf" 2>&1 &
    fi
    echo $! >"$(pid_file "$name")"
  )
}

is_running() {
  local f pid; f="$(pid_file "$1")"
  [ -f "$f" ] || return 1
  pid="$(cat "$f" 2>/dev/null || true)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

wait_for() {
  local url="$1" name="$2" tries="${3:-90}" i
  for ((i = 1; i <= tries; i++)); do
    up "$url" && { log "$name 就绪：$url"; return 0; }
    sleep 1
  done
  die "$name 启动超时，请查看 $LOG_DIR/$name.log"
}

start_db() {
  [ "$START_DB" = "1" ] || { warn "START_DB=0，跳过本地数据库启动"; return 0; }
  if ! command -v docker >/dev/null 2>&1; then
    warn "未找到 docker，跳过本地 PG（假定 WENJING_DATABASE_URL 指向的数据库可用）"
    return 0
  fi
  log "启动 PostgreSQL (docker compose up -d db) ..."
  (cd "$ROOT" && docker compose up -d db) \
    || warn "docker compose 启动 db 失败，继续（假定外部 PG 可用）"
  # 等 db 健康（最多 ~30s）
  local i
  for ((i = 1; i <= 30; i++)); do
    docker compose ps db 2>/dev/null | grep -q "healthy" && { log "PostgreSQL 就绪"; return 0; }
    sleep 1
  done
  warn "未确认 PostgreSQL 健康，继续启动服务"
}

migrate() {
  [ -f "$BACKEND_DIR/.env" ] || {
    log "backend/.env 不存在，从 .env.example 复制"
    cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
  }
  log "运行 Alembic 迁移 ..."
  (cd "$BACKEND_DIR" && uv run alembic upgrade head) || die "Alembic 迁移失败"
}

start_backend() {
  if up "$BACKEND_URL/health/live"; then log "backend 已在运行：$BACKEND_URL"; return 0; fi
  log "启动 backend → $BACKEND_URL（日志 $LOG_DIR/backend.log）"
  spawn backend "$BACKEND_DIR" "$LOG_DIR/backend.log" \
    uv run uvicorn app.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT"
  wait_for "$BACKEND_URL/health/live" backend
}

start_frontend() {
  if up "$FRONTEND_URL"; then log "frontend 已在运行：$FRONTEND_URL"; return 0; fi
  if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    log "安装 frontend 依赖 (npm install) ..."
    (cd "$FRONTEND_DIR" && npm install) || die "npm install 失败"
  fi
  log "启动 frontend → $FRONTEND_URL（日志 $LOG_DIR/frontend.log）"
  spawn frontend "$FRONTEND_DIR" "$LOG_DIR/frontend.log" \
    npm run dev -- --hostname "$FRONTEND_HOST" --port "$FRONTEND_PORT"
  wait_for "$FRONTEND_URL" frontend
}

stop_one() {
  local name="$1" f pid
  f="$(pid_file "$name")"
  if [ ! -f "$f" ]; then log "$name 未在运行（无 pid 文件）"; return 0; fi
  pid="$(cat "$f" 2>/dev/null || true)"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    log "停止 $name (pgid $pid)"
    kill -TERM -- "-$pid" 2>/dev/null || {
      kill "$pid" 2>/dev/null || true
      pkill -P "$pid" 2>/dev/null || true
    }
    sleep 2
    kill -KILL -- "-$pid" 2>/dev/null || true
    kill -9 "$pid" 2>/dev/null || true
  else
    warn "$name pid $pid 已不存在"
  fi
  rm -f "$f"
}

status() {
  if up "$BACKEND_URL/health/live"; then log "backend  运行中  $BACKEND_URL"; else warn "backend  未运行"; fi
  if up "$FRONTEND_URL"; then log "frontend 运行中  $FRONTEND_URL"; else warn "frontend 未运行"; fi
}

cmd_start() {
  start_db
  migrate
  start_backend
  start_frontend
  echo
  log "完成：前端 $FRONTEND_URL  后端 $BACKEND_URL"
  log "停止：./scripts/dev.sh stop   查看日志：./scripts/dev.sh logs"
}

cmd_stop() { stop_one frontend; stop_one backend; }

cmd_logs() {
  local which="${1:-all}"
  case "$which" in
    backend)  tail -n 100 -f "$LOG_DIR/backend.log" ;;
    frontend) tail -n 100 -f "$LOG_DIR/frontend.log" ;;
    all)      tail -n 50 -f "$LOG_DIR/backend.log" "$LOG_DIR/frontend.log" ;;
    *) die "logs 参数：backend | frontend | all" ;;
  esac
}

case "${1:-start}" in
  start)   cmd_start ;;
  stop)    cmd_stop ;;
  restart) cmd_stop; cmd_start ;;
  status)  status ;;
  logs)    shift; cmd_logs "${1:-all}" ;;
  *) die "用法：$0 [start|stop|restart|status|logs [backend|frontend|all]]" ;;
esac
