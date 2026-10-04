#!/usr/bin/env bash
#
# 蓝绿发布流量切换 / 回滚脚本
# 用法:
#   ./bluegreen.sh switch blue    # 全量切到 blue
#   ./bluegreen.sh switch green   # 全量切到 green
#   ./bluegreen.sh split          # 新旧各 50% 流量
#   ./bluegreen.sh rollback       # 回滚到上一版(读状态文件自动反向切换)
#   ./bluegreen.sh status         # 查看当前流量状态
#
set -euo pipefail

# ============ 配置区(按实际环境修改) ============
NGINX_CONF="/etc/nginx/conf.d/app-upstream.conf"   # nginx upstream 配置片段
STATE_FILE="/var/lib/bluegreen/active.state"       # 当前激活版本状态文件
HEALTH_BLUE="http://127.0.0.1:9001/health"         # blue 健康检查
HEALTH_GREEN="http://127.0.0.1:9002/health"        # green 健康检查
NGINX_BIN=$(command -v nginx || echo "/usr/sbin/nginx")
# ================================================

mkdir -p "$(dirname "$STATE_FILE")"

log() { echo "[$(date '+%F %T')] $*"; }

get_active() {
    if [[ -f "$STATE_FILE" ]]; then
        cat "$STATE_FILE"
    else
        echo "none"
    fi
}

# 健康检查: 连续 3 次失败视为不健康
check_health() {
    local url="$1" fails=0
    for _ in $(seq 1 3); do
        if ! curl -fsS --max-time 3 "$url" >/dev/null 2>&1; then
            fails=$((fails+1))
        fi
        sleep 1
    done
    [[ $fails -lt 3 ]]
}

other() { [[ "$1" == "blue" ]] && echo "green" || echo "blue"; }

# 根据 active 版本与目标模式生成 upstream 配置
write_conf() {
    local active="$1" mode="$2"   # mode: full(全量) / split(对半)
    local blue_port=9001 green_port=9002

    if [[ "$mode" == "full" ]]; then
        if [[ "$active" == "blue" ]]; then
            cat > "$NGINX_CONF" <<EOF
upstream app {
    server 127.0.0.1:${blue_port} weight=1 max_fails=3 fail_timeout=10s;
    server 127.0.0.1:${green_port} down;
}
EOF
        else
            cat > "$NGINX_CONF" <<EOF
upstream app {
    server 127.0.0.1:${blue_port} down;
    server 127.0.0.1:${green_port} weight=1 max_fails=3 fail_timeout=10s;
}
EOF
        fi
    else
        cat > "$NGINX_CONF" <<EOF
upstream app {
    server 127.0.0.1:${blue_port} weight=1 max_fails=3 fail_timeout=10s;
    server 127.0.0.1:${green_port} weight=1 max_fails=3 fail_timeout=10s;
}
EOF
    fi
}

reload_nginx() {
    "$NGINX_BIN" -t && "$NGINX_BIN" -s reload
}

switch_to() {
    local target="$1" mode="${2:-full}" current
    current=$(get_active)

    log "健康检查: $target ..."
    if [[ "$target" == "blue" ]]; then
        check_health "$HEALTH_BLUE" || { log "错误: $target 健康检查未通过,放弃切换"; exit 1; }
    else
        check_health "$HEALTH_GREEN" || { log "错误: $target 健康检查未通过,放弃切换"; exit 1; }
    fi

    log "写入配置: 目标=$target, 模式=$mode"
    write_conf "$target" "$mode"
    reload_nginx || { log "错误: nginx reload 失败,请人工介入"; exit 1; }

    echo "$target" > "$STATE_FILE"
    log "已切换: $current -> $target (mode=$mode)"
}

rollback() {
    local current
    current=$(get_active)
    if [[ "$current" == "none" ]]; then
        log "无历史状态可回滚"; exit 1
    fi
    log "回滚: $current -> $(other "$current")"
    switch_to "$(other "$current")" full
}

status() {
    local active
    active=$(get_active)
    log "当前激活版本: $active"
    if [[ -f "$NGINX_CONF" ]]; then
        echo "---- nginx upstream 配置 ----"
        cat "$NGINX_CONF"
    fi
}

case "${1:-}" in
    switch)
        [[ "${2:-}" =~ ^(blue|green)$ ]] || { echo "用法: $0 switch blue|green"; exit 1; }
        switch_to "$2" full
        ;;
    split)
        switch_to "$(get_active)" split
        ;;
    rollback)
        rollback
        ;;
    status)
        status
        ;;
    *)
        grep -E '^#\s+(用法|\./)' "$0" | sed 's/^#//'
        exit 1
        ;;
esac
