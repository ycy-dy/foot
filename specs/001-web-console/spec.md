# Feature Specification: 竞彩分析推荐 Web 控制台

**Feature Branch**: `001-web-console` | **Created**: 2026-11-04 | **Status**: In Progress（阶段1完成）
**Input**: 用户需求原文与确认事项见 `source-prompt.md`。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 钉钉登录与白名单 (Priority: P1)
白名单用户在局域网内用浏览器打开 `http://<本机IP>:5020`，用钉钉登录后进入系统；非白名单成员被拒绝，并看到自己的 userId，便于管理员加入白名单。
**Independent Test**: 模拟钉钉身份交换，验证允许、拒绝、白名单移除后失效、admin/viewer 权限。
**Acceptance**: 1) 未登录访问任意页面会跳转登录页，API 返回401；2) state 无效或超时则拒绝；3) 拒绝页显示 userId 并写审计日志。

### User Story 2 - 今日赛程与市场基准 (Priority: P1)
用户查看当天（业务日）足球赛程（分早/中/晚场，窗口外单列）和篮球赛程（客队在前、主队在后），每个玩法显示赔率和 p_mkt，可进入单场详情。
**Independent Test**: 用固定的官方快照渲染页面和 API。
**Acceptance**: 数据带快照时间；官方接口失败时回退到最近快照并提示。

### User Story 3 - 最终推荐汇总展示 (Priority: P1)
首页顶部显示当前业务日最新的“最终推荐汇总”（V6 第20.10节），可查看完整报告。

### User Story 4 - Claude Agent 分析任务 (Priority: P2)
admin 点击按钮或由定时任务触发，调用本机 `claude -p` 按体系完成分析，输出结构化 JSON 和报告。审核通过后发布为新版本，失败时如实显示。

2026-11-04 追加：重新分析按钮优先 Claude，调用异常/不可用时回退 Codex，执行与草稿交付见 `../004-analysis-fallback/`。自动审核发布和定时触发仍按后续阶段单独实施。

### User Story 5 - 定时任务与钉钉推送 (Priority: P2)
定时生成分析、开赛前复核、次日复盘。定时任务的结果在前端可见，并通过工作通知推送给指定用户；复核只在有变化时推送。

### User Story 6 - 复盘与命中率台账 (Priority: P3)
按原发布版本逐场结算，更新台账，网页上查看历史版本和命中率。

### Edge Cases
- 钉钉接口失败、成员未激活、回调地址或 IP 变化。
- 官方接口无数据或格式变化；篮球无赛程。
- 同一时间多次触发分析（需排队并加锁）；claude 命令行未登录或额度用尽。
- Mac 休眠导致错过定时任务（需补跑策略和告警）。

## Requirements *(mandatory)*

### Functional Requirements
- **FR-001** 钉钉 OAuth2 登录，复用 version_ctrl_console 的应用；只允许白名单用户；分 admin 和 viewer 两种角色。
- **FR-002** 拒绝页显示钉钉 userId 和姓名；登录、拒绝、登出都写审计日志。
- **FR-003** 抓取竞彩官方足球、篮球计算器数据，每次保存不可覆盖的快照，并带内存缓存；失败时回退到最近快照。
- **FR-004** 按 V6 口径计算 p_mkt（比例去水）、足球分段、双平复合、最高相邻总进球、比分参考、18.6.1 触发标记。
- **FR-005** 首页展示最终推荐汇总、足球和篮球赛程；提供单场详情、完整报告和 `/api/today`。
- **FR-006** Agent 任务：同一时间只运行一个，可设超时，日志可追溯，输出固定 schema，必须审核通过才能发布，并保留版本。
- **FR-007** 调度：按钮和定时两种方式，时间可配置并持久化；任务记录触发来源。
- **FR-008** 钉钉工作通知推送（AgentId 已配置）：定时结果、需复核变化、失败告警，失败时重试。
- **FR-009** 复盘结算与台账页面。

### Non-Functional Requirements
- **NFR-001** 可靠性：launchd 守护并自动重启；外部依赖失败可降级；任务不重复执行。
- **NFR-002** 安全：密钥只放 `.env`；cookie 设 HttpOnly 和 SameSite；校验 CSRF；加安全响应头。
- **NFR-003** 可扩展：分层包结构，新增 engine/scheduler/notify 子包时不改动现有层。
- **NFR-004** 移动端可读。

### Key Entities
- **Snapshot**：抓取的原始 JSON，带时间、sha256 和来源更新时间。
- **Event**：审计日志。
- **Run（阶段4）**：分析任务，记录触发来源、状态、日志、输出、审核结果和替代关系。
- **Schedule（阶段5）**、**Notification（阶段5）**。

## Success Criteria *(mandatory)*
- **SC-001** 白名单用户在手机或电脑上10秒内看到当日赛程和推荐汇总。
- **SC-002** 非白名单用户无法访问任何业务页面或 API（有自动化测试覆盖）。
- **SC-003** 未通过审核的推荐不会显示为“已发布”，也不会推送。
- **SC-004** 全量 pytest 通过，外部依赖全部可模拟。

## Assumptions
- 本机局域网 IP 当前为 172.16.37.247，回调地址已在钉钉开放平台登记。
- 运行服务的用户就是已登录 claude 命令行的用户（ycy）。
