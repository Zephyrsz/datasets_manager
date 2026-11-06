#!/usr/bin/env bash
# Manage the local FastAPI + Vite services from any working directory.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$ROOT/.run"
LOG_DIR="$ROOT/.logs"
PYTHON="$ROOT/.venv/bin/python"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
START_TIMEOUT="${START_TIMEOUT:-30}"
STOP_TIMEOUT="${STOP_TIMEOUT:-10}"
STARTED=()
LOCKED=0

usage() {
    cat <<'EOF'
用法: ./start.sh [start|stop|restart|status|help]
  start    后台启动前后端（默认）；首次运行自动安装依赖
  stop     停止本脚本管理的前后端及其子进程
  restart  停止后重新启动全部服务
  status   查看前后端运行状态；未全部运行时返回非零状态码

环境变量:
  BACKEND_PORT   后端端口，默认 8000
  FRONTEND_PORT  前端端口，默认 5173
  PYTHON_BIN     创建 .venv 使用的 Python，默认 python3（3.10+）
  START_TIMEOUT 各服务启动等待秒数，默认 30
  STOP_TIMEOUT  各服务优雅停止等待秒数，默认 10
日志: .logs/backend.log、.logs/frontend.log；进程记录: .run/
EOF
}

fail() { printf '错误: %s\n' "$*" >&2; return 1; }

# The start time and command protect unrelated processes from stale/reused PIDs.
process_identity() { ps -ww -p "$1" -o lstart= -o command= 2>/dev/null; }

# An inherited random token also identifies surviving children after the leader dies.
# Never trust a stale process-group number on its own: it can eventually be reused.
owned_group_pid() {
    local file="$RUN_DIR/$1.pid" pid saved token member environment
    [[ -f "$file" ]] || return 1
    { IFS= read -r pid; IFS= read -r saved; IFS= read -r token; } < "$file" || true
    [[ "${pid:-}" =~ ^[0-9]+$ ]] && (( pid > 1 )) \
        && [[ "${token:-}" =~ ^[a-f0-9]{32}$ ]] || return 1
    while IFS= read -r member; do
        environment="$(ps eww -p "$member" -o command= 2>/dev/null)" || continue
        case " $environment " in
            *" DATASETS_MANAGER_TOKEN=$token "*) printf '%s\n' "$pid"; return 0 ;;
        esac
    done < <(ps -axo pid=,pgid=,stat= | awk -v group="$pid" \
        '$2 == group && $3 !~ /^Z/ { print $1 }')
    return 1
}

service_pid() {
    local file="$RUN_DIR/$1.pid" pid saved current
    [[ -f "$file" ]] || return 1
    { IFS= read -r pid; IFS= read -r saved; } < "$file" || true
    if [[ "${pid:-}" =~ ^[0-9]+$ ]] && (( pid > 1 )) && [[ -n "${saved:-}" ]]; then
        current="$(process_identity "$pid")" || current=""
        if [[ "$current" == "$saved" ]] && kill -0 "$pid" 2>/dev/null; then
            printf '%s\n' "$pid"
            return 0
        fi
    fi
    # Keep a crashed leader's record while a verifiably owned group survives.
    owned_group_pid "$1" >/dev/null || rm -f -- "$file"
    return 1
}

group_alive() {
    ps -axo pgid=,stat= | awk -v group="$1" \
        '$1 == group && $2 !~ /^Z/ { found = 1 } END { exit !found }'
}

stop_service() {
    local name="$1" pid deadline
    if ! pid="$(service_pid "$name")"; then
        if ! pid="$(owned_group_pid "$name")"; then
            printf '%s 已停止。\n' "$name"
            return 0
        fi
        printf '%s 主进程已退出，正在清理残留子进程。\n' "$name"
    fi
    printf '正在停止 %s (PID %s)...\n' "$name" "$pid"
    kill -TERM -- "-$pid" 2>/dev/null || true
    deadline=$((SECONDS + STOP_TIMEOUT))
    while group_alive "$pid"; do
        if (( SECONDS >= deadline )); then
            kill -KILL -- "-$pid" 2>/dev/null || true
            sleep 0.2
            if group_alive "$pid"; then
                fail "$name 停止失败，保留进程记录供检查。"
                return 1
            fi
            break
        fi
        sleep 0.2
    done
    rm -f -- "$RUN_DIR/$name.pid"
    printf '%s 已停止。\n' "$name"
}

cleanup() {
    local result=$? name
    trap - EXIT
    set +e
    if (( result != 0 && ${#STARTED[@]} > 0 )); then
        printf '启动未完成，正在清理本次启动的服务...\n' >&2
        for name in "${STARTED[@]}"; do stop_service "$name"; done
    fi
    if (( LOCKED )); then
        rm -f -- "$RUN_DIR/control.lock/owner"
        rmdir -- "$RUN_DIR/control.lock"
    fi
    exit "$result"
}

acquire_lock() {
    local owner
    mkdir -p -- "$RUN_DIR"
    if ! mkdir -- "$RUN_DIR/control.lock" 2>/dev/null; then
        owner="$(cat "$RUN_DIR/control.lock/owner" 2>/dev/null)" || owner=""
        if [[ "$owner" =~ ^[0-9]+$ ]] && ! kill -0 "$owner" 2>/dev/null; then
            rm -f -- "$RUN_DIR/control.lock/owner"
            rmdir -- "$RUN_DIR/control.lock" 2>/dev/null || true
            mkdir -- "$RUN_DIR/control.lock" 2>/dev/null || { fail '另一个启停操作正在执行。'; return 1; }
        else
            fail '另一个启停操作正在执行；若上次被强制中断，请检查 .run/control.lock。'
            return 1
        fi
    fi
    LOCKED=1
    printf '%s\n' "$$" > "$RUN_DIR/control.lock/owner"
}

prepare_dependencies() {
    local bootstrap="${PYTHON_BIN:-python3}"
    command -v node >/dev/null 2>&1 || { fail '请先安装 Node.js 20.19+ 或 22.12+。'; return 1; }
    node -e 'const [major, minor] = process.versions.node.split(".").map(Number); process.exit((major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major > 22 ? 0 : 1)' \
        || { fail 'Node.js 版本不满足要求，请使用 20.19+、22.12+ 或更新 LTS。'; return 1; }
    if [[ ! -x "$PYTHON" ]]; then
        command -v "$bootstrap" >/dev/null 2>&1 || { fail '找不到 Python，请安装 Python 3.10+ 或设置 PYTHON_BIN。'; return 1; }
        "$bootstrap" -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
            || { fail '需要 Python 3.10+。'; return 1; }
        printf '正在创建 Python 虚拟环境...\n'
        "$bootstrap" -m venv "$ROOT/.venv"
    fi
    "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
        || { fail '.venv 需要使用 Python 3.10+。'; return 1; }
    if ! "$PYTHON" -c 'import fastapi, uvicorn' >/dev/null 2>&1; then
        printf '正在安装后端依赖...\n'
        "$PYTHON" -m pip install -r "$ROOT/requirements.lock"
    fi
    if [[ ! -f "$ROOT/frontend/node_modules/vite/bin/vite.js" ]]; then
        command -v npm >/dev/null 2>&1 || { fail '找不到 npm，请先安装 npm。'; return 1; }
        printf '正在安装前端依赖...\n'
        (cd "$ROOT/frontend" && npm ci)
    fi
}

check_ports() {
    local ports=()
    service_pid backend >/dev/null || ports+=("$BACKEND_PORT")
    service_pid frontend >/dev/null || ports+=("$FRONTEND_PORT")
    (( ${#ports[@]} > 0 )) || return 0
    "$PYTHON" - "${ports[@]}" <<'PY'
import socket
import sys
for port in sys.argv[1:]:
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", int(port)))
        except OSError as error:
            sys.exit(f"端口 {port} 不可用: {error}；请检查占用进程或设置 BACKEND_PORT / FRONTEND_PORT。")
PY
}

http_ready() {
    "$PYTHON" - "$1" <<'PY' >/dev/null 2>&1
import sys
from urllib.request import ProxyHandler, build_opener
with build_opener(ProxyHandler({})).open(sys.argv[1], timeout=1) as response:
    sys.exit(response.status != 200)
PY
}

start_service() {
    local name="$1" url="$2" pid identity deadline launch token
    shift 2
    if pid="$(service_pid "$name")"; then
        printf '%s 已运行 (PID %s)。\n' "$name" "$pid"
        return 0
    fi
    # A new session gives each service its own process group, including Vite's children.
    launch="$("$PYTHON" - "$ROOT" "$LOG_DIR/$name.log" "$@" <<'PY'
import os
import secrets
import subprocess
import sys
token = secrets.token_hex(16)
with open(sys.argv[2], "ab", buffering=0) as log:
    process = subprocess.Popen(sys.argv[3:], cwd=sys.argv[1], stdin=subprocess.DEVNULL,
                               stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                               env={**os.environ, "DATASETS_MANAGER_TOKEN": token})
print(process.pid, token)
PY
)"
    read -r pid token <<< "$launch"
    identity="$(process_identity "$pid")" || identity=""
    printf '%s\n%s\n%s\n' "$pid" "$identity" "$token" > "$RUN_DIR/$name.pid"
    STARTED+=("$name")
    printf '正在启动 %s (PID %s)...\n' "$name" "$pid"
    deadline=$((SECONDS + START_TIMEOUT))
    while (( SECONDS < deadline )); do
        service_pid "$name" >/dev/null || break
        if http_ready "$url" && service_pid "$name" >/dev/null; then
            printf '%s 已就绪。\n' "$name"
            return 0
        fi
        sleep 0.2
    done
    fail "$name 启动失败或超时，日志: $LOG_DIR/$name.log"
    tail -n 20 "$LOG_DIR/$name.log" >&2
    return 1
}

start_all() {
    local name
    prepare_dependencies
    for name in backend frontend; do
        if ! service_pid "$name" >/dev/null && [[ -f "$RUN_DIR/$name.pid" ]]; then
            stop_service "$name"
        fi
    done
    check_ports
    mkdir -p -- "$LOG_DIR"
    export DATASETS_BACKEND_URL="http://127.0.0.1:$BACKEND_PORT"
    export FRONTEND_ORIGINS="${FRONTEND_ORIGINS:-http://127.0.0.1:$FRONTEND_PORT,http://localhost:$FRONTEND_PORT}"
    start_service backend "$DATASETS_BACKEND_URL/api/health" \
        "$PYTHON" -m uvicorn backend.main:app --host 127.0.0.1 --port "$BACKEND_PORT"
    start_service frontend "http://127.0.0.1:$FRONTEND_PORT/" \
        node "$ROOT/frontend/node_modules/vite/bin/vite.js" "$ROOT/frontend" \
        --host 127.0.0.1 --port "$FRONTEND_PORT" --strictPort
    printf '\n前端: http://127.0.0.1:%s\nAPI 文档: %s/docs\n日志目录: %s\n' \
        "$FRONTEND_PORT" "$DATASETS_BACKEND_URL" "$LOG_DIR"
}

stop_all() {
    local result=0
    stop_service frontend || result=1
    stop_service backend || result=1
    return "$result"
}

status_all() {
    local name pid result=0
    for name in backend frontend; do
        if pid="$(service_pid "$name")"; then
            printf '%s 运行中 (PID %s)。\n' "$name" "$pid"
        else
            printf '%s 未运行。\n' "$name"
            result=1
        fi
    done
    return "$result"
}

(( $# <= 1 )) || { usage >&2; exit 2; }
ACTION="${1:-start}"
case "$ACTION" in
    help|-h|--help) usage; exit 0 ;;
    start|stop|restart|status) ;;
    *) usage >&2; exit 2 ;;
esac
for value in "$BACKEND_PORT" "$FRONTEND_PORT" "$START_TIMEOUT" "$STOP_TIMEOUT"; do
    [[ "$value" =~ ^[1-9][0-9]{0,4}$ ]] || { fail '端口和超时时间必须为正整数（最多 5 位）。'; exit 2; }
done
(( BACKEND_PORT <= 65535 && FRONTEND_PORT <= 65535 && BACKEND_PORT != FRONTEND_PORT )) \
    || { fail '前后端端口必须不同，且范围为 1–65535。'; exit 2; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
cd "$ROOT"
acquire_lock
case "$ACTION" in
    start) start_all ;;
    stop) stop_all ;;
    restart) stop_all; start_all ;;
    status) status_all ;;
esac
