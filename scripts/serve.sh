#!/usr/bin/env bash
# 一条命令把本机演示拉起来：Redis → FastAPI → Nginx（如果配好了站点）。
#
#   ./scripts/serve.sh up       # 起服务并做验收
#   ./scripts/serve.sh status   # 看进程和监听
#   ./scripts/serve.sh down     # 停 API 和 Nginx（Redis 不动，别的项目也可能在用）
#
# 说明：
# - API 固定绑 127.0.0.1，公网入口只留 Nginx 一个，token 由 Nginx 注入。
# - 环境变量仍然从仓库根的 .env 读（api.py 里的 load_dotenv 负责），脚本不打印任何 key。
# - Nginx 站点配置不存在时脚本只提示，不会替你猜 token。
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1

STATE_DIR="$ROOT/.serve"
PID_FILE="$STATE_DIR/api.pid"
LOG_FILE="$ROOT/api.log"
HOST="${MINGLI_HOST:-127.0.0.1}"
PORT="${MINGLI_PORT:-8000}"
WORKERS="${MINGLI_WORKERS:-2}"
REDIS_URL="${MINGLI_REDIS_URL:-redis://127.0.0.1:6379/0}"

info() { printf '[serve] %s\n' "$*"; }
fail() { printf '[serve] 失败：%s\n' "$*" >&2; exit 1; }

pick_python() {
    if [ -x "$ROOT/.venv/bin/python" ]; then
        echo "$ROOT/.venv/bin/python"
    elif command -v python3 >/dev/null 2>&1; then
        command -v python3
    elif command -v python >/dev/null 2>&1; then
        command -v python
    else
        fail "找不到 python"
    fi
}

start_redis() {
    if command -v redis-cli >/dev/null 2>&1 && [ "$(redis-cli ping 2>/dev/null)" = "PONG" ]; then
        info "Redis 已在运行"
        return
    fi
    if command -v redis-server >/dev/null 2>&1; then
        redis-server --daemonize yes >/dev/null 2>&1 || true
        sleep 1
        if [ "$(redis-cli ping 2>/dev/null)" = "PONG" ]; then
            info "Redis 已启动"
        else
            info "Redis 没起来：回答闸门会退化为进程内 20 槽（/health 里 backend 会显示 local）"
        fi
    else
        info "没装 redis-server：闸门退化为进程内，单 worker 也能演示"
    fi
}

stop_api() {
    if [ -f "$PID_FILE" ]; then
        kill "$(cat "$PID_FILE")" 2>/dev/null || true
        rm -f "$PID_FILE"
    fi
    pkill -f 'src/api.py' 2>/dev/null || true
    sleep 1
}

start_api() {
    stop_api
    command -v curl >/dev/null 2>&1 || fail "需要 curl"
    mkdir -p "$STATE_DIR"
    local py
    py="$(pick_python)"
    info "启动 API：$HOST:$PORT，$WORKERS worker，Redis=$REDIS_URL"
    MINGLI_HOST="$HOST" MINGLI_PORT="$PORT" MINGLI_WORKERS="$WORKERS" \
        MINGLI_REDIS_URL="$REDIS_URL" \
        nohup "$py" src/api.py >"$LOG_FILE" 2>&1 &
    echo $! >"$PID_FILE"

    local i
    for i in $(seq 1 60); do
        if curl -sf "http://$HOST:$PORT/health" >/dev/null 2>&1; then
            info "API 就绪（第 $((i * 2)) 秒）"
            return
        fi
        sleep 2
    done
    tail -20 "$LOG_FILE" >&2 || true
    fail "API 120 秒内没就绪，看 $LOG_FILE"
}

start_nginx() {
    if ! command -v nginx >/dev/null 2>&1; then
        info "没装 nginx：跳过。公网入口需要按 deploy/README.md §6 配置"
        return
    fi
    if [ ! -f /etc/nginx/sites-enabled/mingli ]; then
        info "站点配置 /etc/nginx/sites-enabled/mingli 不存在：跳过"
        info "生成方法见 deploy/README.md §6（token 从 .env 注入，不要写进仓库）"
        return
    fi
    if ! sudo -n nginx -t >/dev/null 2>&1; then
        info "nginx -t 需要 sudo 或配置有误，手动跑：sudo nginx -t"
        return
    fi
    if sudo -n nginx -s reload >/dev/null 2>&1 || sudo -n nginx >/dev/null 2>&1; then
        info "Nginx 已生效"
    else
        info "Nginx 起不来，手动跑：sudo nginx -t && sudo nginx -s reload"
    fi
}

check() {
    command -v curl >/dev/null 2>&1 || return
    info "验收（期望 401 / 404 / 404 / 200）"
    printf '  api-direct  %s\n' "$(curl -s -o /dev/null -w '%{http_code}' "http://$HOST:$PORT/trace/x" 2>/dev/null)"
    printf '  via-nginx   %s\n' "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/api/trace/x 2>/dev/null)"
    printf '  metrics     %s\n' "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/metrics 2>/dev/null)"
    printf '  frontend    %s\n' "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/ 2>/dev/null)"
}

status() {
    info "监听："
    if command -v ss >/dev/null 2>&1; then
        ss -ltn | grep -E ":($PORT|80)\b" || echo "  （没有 $PORT 或 80）"
    elif command -v netstat >/dev/null 2>&1; then
        netstat -ltn 2>/dev/null | grep -E ":($PORT|80)\b" || echo "  （没有 $PORT 或 80）"
    else
        echo "  （没有 ss/netstat，跳过）"
    fi
    if curl -sf "http://$HOST:$PORT/health" >/dev/null 2>&1; then
        info "API 健康"
        curl -s "http://$HOST:$PORT/health" | head -c 400
        echo
    else
        info "API 不健康"
    fi
}

case "${1:-up}" in
    up)
        start_redis
        start_api
        start_nginx
        check
        ;;
    down)
        stop_api
        if command -v sudo >/dev/null 2>&1; then
            sudo -n nginx -s stop >/dev/null 2>&1 || true
        fi
        info "已停止 API 和 Nginx（Redis 保留）"
        ;;
    status)
        status
        ;;
    *)
        fail "用法：$0 [up|down|status]"
        ;;
esac
