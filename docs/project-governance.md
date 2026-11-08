# 项目驱动规范与阅读地图

更新：2026-11-06。用户后续确认原推荐要求及70%证据硬门槛并授权实施，现行政策为[规格014](../specs/014-evidence-gated-recommendations/spec.md)。旧停用状态见013为历史过程，不再覆盖014。始终不授权投注或自动发送。

## 1. 规范层级

| 层级 | 权威文件 | 当前作用 |
| --- | --- | --- |
| Agent 执行入口 | [AGENTS.md](../AGENTS.md)；[CLAUDE.md](../CLAUDE.md) | 阅读顺序、操作边界和工作区规则 |
| 业务政策 | [014政策](../specs/014-evidence-gated-recommendations/policy.md)、[YAML](../specs/014-evidence-gated-recommendations/policy.yaml)、[评分](../specs/014-evidence-gated-recommendations/scoring.md) | 证据>=70、分段/结构/审核及冻结日台账 |
| 工程治理 | [宪法](../.specify/memory/constitution.md) | 安全、真实数据、历史冻结、测试和变更流程 |
| 功能交付 | [规格目录](../specs/)内各项 spec → plan → tasks → verification | 旧实现记录或新规格的交付证据，不自动构成业务授权 |

系统／开发者／用户直接指令优先级不变。旧 V6 阈值、玩法、维度、推荐结构和页面均不再是当前规则，不能从旧文档、Git 历史或运行工件恢复。`specs/001`–`specs/012` 仅作旧实现记录；规格006目录已删除，不能建立链接。`history/` 已删除且不恢复。

## 2. 当前状态与阅读方式

- 产品认知、工程安全、不投注、真实数据和运行工件冻结边界继续有效。
- 手动分析、AI决策与人工审核发布按014实施；自动计划与通知默认停用，不因部署自动启用。每日推荐台账见[daily-recommendations](daily-recommendations.md)。
- 运行工件（包括 `runs/`、`ledger/`、`var/`）只读核对，不删除、不改写、不据此生成当前政策。
- 接手或开发：入口 → 本文 → 宪法 → [目录约定](directory-layout.md) → 对应规格；先检查已有改动。
- 规格修改：用户明确变更 → 规格013（或后续规格）→ 计划、任务、实现、测试和审核门禁；文档保存不等于运行时完成。

## 3. 规格索引（旧实现记录）

| 编号 | 主题 | 当前定位 |
| --- | --- | --- |
| [001](../specs/001-web-console/spec.md) | Web 控制台 | 旧实现记录 |
| [002](../specs/002-ui-polish/spec.md) | UI 优化 | 旧实现记录 |
| [003](../specs/003-multi-origin-login/spec.md) | 多入口登录 | 旧实现记录 |
| [004](../specs/004-analysis-fallback/spec.md) | 分析回退 | 旧实现记录 |
| [005](../specs/005-analysis-live-logs/spec.md) | 分析日志 | 旧实现记录 |
| [007](../specs/007-scheduled-review/spec.md) | 定时与复盘 | 旧实现记录 |
| [008](../specs/008-research-workflow/spec.md) | 研究闭环 | 旧实现记录 |
| [009](../specs/009-ai-decisions/spec.md) | AI 决策契约 | 旧实现记录 |
| [010](../specs/010-functional-hardening/spec.md) | 功能加固 | 旧实现记录 |
| [011](../specs/011-task-actions/spec.md) | 任务操作 | 旧实现记录 |
| [012](../specs/012-sports-agent-system/spec.md) | Agent 产品与规范 | 旧实现记录 |
| 013 | 移除当前业务政策 | 历史过程，014已重新授权当前政策 |
| [034](../specs/034-system-functional-verification/spec.md) | 全功能与页面控制件验证 | [验收矩阵](../specs/034-system-functional-verification/functional-matrix.md)，限定范围证据与未完成项 |

## 4. 交付状态语言

- **已定义**：有规格，没有完成实现／验收证据。
- **已实现，待验收**：有代码或离线测试，尚未完成真实依赖和全链路验收。
- **已验证（限定范围）**：列明命令、日期、环境、模拟或真实、结果和证据。
- **受阻／失败**：保留失败原因，不把运行结束标成推理成功。

本文不宣称生产可用性、盈利或部署完成。目标 Agent 架构与职责边界见[系统蓝图](sports-agent-system.md)。
