#!/bin/zsh
# 启动竞彩分析推荐 Web 系统（本机，gunicorn，0.0.0.0:${FOOT_PORT:-5020}）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PORT="$(grep -E '^FOOT_PORT=' .env 2>/dev/null | cut -d= -f2)"; PORT="${PORT:-5020}"
mkdir -p var/logs
exec "$ROOT/.venv/bin/gunicorn" 'foot_web.wsgi:app' \
  --bind "0.0.0.0:${PORT}" --workers 2 --threads 4 --timeout 60 \
  --access-logfile var/logs/access.log --error-logfile var/logs/error.log
