# Implementation Plan: 竞彩分析推荐 Web 控制台

**Branch**: `001-web-console` | **Date**: 2026-11-04 | **Spec**: `spec.md`

## Summary
用 Flask 在本机实现钉钉登录、今日赛程、推荐汇总展示（阶段1–3）；随后接入 `claude -p` 分析任务、定时调度、钉钉推送和复盘（阶段4–6）。

2026-11-04 追加实施：按钮后台分析按 `specs/004-analysis-fallback/` 优先 Claude、异常回退 Codex，已有任务状态和独立草稿；自动审核发布仍是后续工作。

## Technical Context
- **Language**: Python 3.12（uv 管理 `.venv`）；**Deps**: Flask、requests、gunicorn、markdown；**Test**: pytest
- **Storage**: SQLite（`var/app.db`），快照放在 `var/snapshots/`，日志放在 `var/logs/`
- **Platform**: macOS 本机，launchd 守护，端口 5020
- **外部**: 钉钉 OAuth2 与工作通知、竞彩官方接口、本机 `claude` 命令行

## Constitution Check
I 规则来源单一 ✅（代码只读体系文档，审核用 tools/）｜II 真实数据 ✅（快照、缺失显示—）｜III 审核门禁 ✅（阶段4强制）｜IV 不投注 ✅｜V 历史冻结 ✅（history/ 只读，runs/ 新版本）｜VI 测试先行 ✅（19个测试）｜VII 安全 ✅（.env 权限600、白名单、审计日志）

## Project Structure

```text
specs/001-web-console/      spec.md plan.md tasks.md source-prompt.md
src/foot_web/
  __init__.py               create_app（应用工厂，注册扩展与蓝图）
  wsgi.py                   gunicorn 入口
  core/config.py            .env 读取、路径（PROJECT_DIR、var/）
  storage/db.py             SQLite 审计日志（阶段4起增加 runs/schedules/notifications）
  data/fetcher.py           官方接口抓取、快照、缓存、回退
  data/markets.py           p_mkt 与赛程展示模型
  services/reports.py       报告和汇总读取（runs/ → history/daily/）
  auth/dingtalk.py          钉钉身份交换（阶段5复用 corp token 推送）
  auth/routes.py            登录、白名单、角色、CSRF
  web/routes.py             页面与 API
  templates/ static/
  [阶段4] engine/           runner.py（claude -p 子进程、锁、超时）、schema.py、publish.py（审核与版本）
  [阶段5] scheduler/        APScheduler 和持久化配置；notify/dingtalk_push.py
tests/                      conftest（Fake 钉钉/抓取）、test_auth、test_pages、test_markets、test_audit_tool
tools/                      audit_recommendations.py、hitrate_backtest.py、restructure_2026_11_04.py
deploy/                     start.sh、com.ycy.foot-web.plist
```

## Complexity Tracking
| 决策 | 理由 | 被否方案 |
| --- | --- | --- |
| 服务端模板，不用前端框架 | 页面以表格为主，部署简单 | React/Vue：需要构建链，增加维护负担 |
| `claude -p` 子进程而非 SDK | 用户要求用本机已登录账号 | Agent SDK 加 API Key：需要按量计费 |
| SQLite | 单机、低并发 | PostgreSQL：运维成本高 |
