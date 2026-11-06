#!/bin/zsh
# 安装/更新 launchd 守护（登录即启动、崩溃自动重启）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL=com.ycy.foot-web
DST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/var/logs"
cp "$ROOT/deploy/$LABEL.plist" "$DST"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$DST"
launchctl enable "gui/$(id -u)/$LABEL"
"$ROOT/deploy/restart.sh" --wait-only
