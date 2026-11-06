#!/bin/zsh
# 代码或 .env 更新后重启服务并等待健康检查通过
set -euo pipefail
LABEL=com.ycy.foot-web
PORT="$(grep -E '^FOOT_PORT=' "$(dirname "$0")/../.env" 2>/dev/null | cut -d= -f2)"; PORT="${PORT:-5020}"
[[ "${1:-}" == "--wait-only" ]] || launchctl kickstart -k "gui/$(id -u)/$LABEL"
for i in {1..30}; do
  if curl -fsS "http://127.0.0.1:${PORT}/healthz" >/dev/null 2>&1; then
    echo "服务已就绪：http://127.0.0.1:${PORT}（pid $(launchctl print gui/$(id -u)/$LABEL | awk '/pid =/{print $3; exit}')）"; exit 0
  fi
  sleep 1
done
echo "服务30秒内未就绪，查看 var/logs/error.log 和 var/logs/launchd.err.log" >&2; exit 1
