# Tasks: 竞彩分析推荐 Web 控制台

格式：`[ID] [P?] [Story] 描述`。勾选表示已完成，并在当次运行中验证过。

## Phase 1: Setup
- [x] T001 安装 Spec Kit（claude 集成）、建立宪法 `.specify/memory/constitution.md`
- [x] T002 目录重构：历史产物 → `history/`，台账 → `ledger/`，工具 → `tools/`，生成迁移对照表 `docs/migration-2026-11-04.md`
- [x] T003 `pyproject.toml`（src 布局）+ `.venv`（uv），`.gitignore` 排除 `.env/.venv/var`

## Phase 2: Foundational
- [x] T004 core/config：读取 `.env`，定义 var/ 路径
- [x] T005 storage/db：审计日志
- [x] T006 data/fetcher：抓取、快照、缓存、失败回退（测试：test_fetcher_falls_back_to_snapshot）

## Phase 3: US1 钉钉登录与白名单 🎯 MVP
- [x] T007 [US1] auth/dingtalk + auth/routes：OAuth2、state 校验、白名单、角色、拒绝页 userId、CSRF 登出
- [x] T008 [US1] tests/test_auth.py（8个用例）
- [x] T009 [US1] 真实钉钉端到端登录验收：2026-11-04 用户登录后先被拒绝，拒绝页显示 userId，加入白名单后具备 admin 权限

## Phase 4: US2/US3 赛程与推荐汇总
- [x] T010 [US2] data/markets：p_mkt、分段、双平、最高相邻总进球、比分参考、18.6.1 触发
- [x] T011 [US2] 首页、详情页、`/api/today`；[US3] 汇总读取 runs/ 与 history/daily/
- [x] T012 tests/test_pages.py、test_markets.py
- [x] T013 本机 gunicorn 运行，局域网地址 172.16.37.247:5020 的 healthz、登录跳转、401 均验证通过（手机端由用户验收）

## Phase 4b: UI 改版与台账统计（2026-11-04 用户追加）
- [x] T026 services/engine：选项枚举、八结构、整单实际倍数>2.5门槛、早中场合并、六类、梦想单（可实时重算）
- [x] T027 services/audit：审核库函数，tools/audit_recommendations.py 改为调用它
- [x] T028 仪表盘六个面板：总览、足球推荐、篮球推荐、八结构推荐、六类方向、逐场分析；“重新分析”按钮（admin + CSRF）
- [x] T029 台账查询（多条件筛选）、历史推荐（按业务日，含已替代版本）、命中率统计（按月、按类别、逐日）
- [x] T030 台账补录 11/4 当前版本并重新结算（203 条，9/23–11/4）
- [x] T031 浅色/深色配色经 validate_palette 校验；桌面与 375px 手机宽度截图检查
- [x] T032 测试 24 个全部通过；重启服务后用实时数据冒烟测试，全部页面返回 200

## Phase 5: US4 Agent 分析任务
2026-11-04 已按 `specs/004-analysis-fallback/` 实现按钮触发的后台执行、Claude→Codex 回退、任务状态和草稿查看。下面的推荐结构 schema、自动审核发布、自动修复与完整任务控制仍按原任务单独验收，未把草稿当作发布完成。

- [ ] T014 engine/schema：推荐 JSON schema（与 tools/audit_recommendations.py 输入一致）
- [ ] T015 engine/runner：`claude -p --output-format stream-json`，文件锁、排队、超时、日志落盘
- [ ] T016 engine/publish：审核 → 版本化写入 `runs/<业务日>/<run_id>/` → 替代关系；失败时自动修正最多2次
- [ ] T017 任务页（admin）：三个按钮、状态、日志
- [ ] T018 测试：模拟 claude 子进程的成功、失败、超时和审核失败路径

## Phase 6: US5 定时与钉钉推送
- [ ] T019 scheduler：APScheduler，时间可配置并持久化，记录触发来源，漏跑时补跑或告警
- [ ] T020 notify：工作通知 asyncsend_v2（markdown 汇总加链接），重试3次，记录日志
- [ ] T021 复核差异检测（停售、低于1.33、低于2.5、撤销条件、推荐替换），只在有变化时推送
- [ ] T022 测试：模拟钉钉推送和调度

## Phase 7: US6 复盘与台账
- [ ] T023 复用 `ledger/data/build_ledgers.py` 的结算逻辑，提供服务化接口和台账页面

## Phase N: Polish
- [x] T024a launchd 守护已安装（install_launchd.sh、restart.sh），kill -9 后自动拉起已验证
- [ ] T024b 防休眠设置（定时任务需要）、部署文档补全
- [ ] T025 `/speckit-analyze` 一致性检查

依赖：T001–T006 → US1 → US2/US3 → US4 → US5 → US6。
