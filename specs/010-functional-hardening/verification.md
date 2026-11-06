# 功能加固验收记录

日期：2026-11-05（北京时间）。规格：[spec.md](spec.md)。

## 结论与未关闭项

**代码回归和隔离核心界面验收通过；真实赛事分析推荐全链路和本轮部署未验收通过。不能宣称“所有功能均已正常上线”。**

- 全量 `.venv/bin/python -m pytest -q`：**236 passed in 78.05s**。
- 提供方/日志专项：**12 passed in 12.09s**。
- 真实Claude和Codex短结构化连通探测均成功；只证明该短输入可返回，不证明长上下文或真实赛事研究成功。
- 官方足球、篮球接口均实时刷新成功（非stale）。抓取时2026-11-05业务日仅1场足球、0场篮球，不能编造第二腿。
- 对唯一可用足球场次进行真实研究：Claude与Codex分别240秒超时，未取得有效证据结果，未进入真实推荐决策阶段，未生成成功草稿。
- `deploy/restart.sh`被工具权限门禁阻断，**本轮未重启/未完成部署验收**。未尝试绕过或修改权限。运行中服务健康仅是现有进程检查。
- 未自动发布、通知、启用生产计划或投注；未改生产白名单、V6原件、已发布原票或历史报告。

## 确证修复与回归

1. **原生Codex配置兼容**：只给MCP条目`enabled=false`仍会在启动时被本机CLI按无效传输拒绝。现在按名称提供结构完整的禁用占位传输`command="/usr/bin/false",args=[]`，不复制原command/env/凭证；保留read-only、执行工具禁用和额外MCP隔离。真实短探测确认修复后可返回。
2. **撤销元数据合并**：台账复盘覆盖层保留原记录的withdrawn/withdrawal_reason及替代关系，不改变冻结原票和确定性结算。先前全量的撤销测试失败已在当前236项回归中通过。
3. **临场AI硬否决漏报**：对已发布的精确match_key+option_id核对带已核实时点来源的veto，生成critical复核变化，涵盖同场第二选项和缓存；无来源意见不升级为事实否决，不自动撤销/换腿。
4. **复盘展示**：保留原leg级p_mkt，复式合计不伪装成每个分项报价；区分旧分项和最终票。
5. **共享AI输入边界**：原始输入和脱敏后输入分别检查2MB限制；不截断证据，超限明确失败。保留真实输入、返回、提供方和哈希验证，不做程序选腿假成功。

## 001–009功能验收矩阵

下列自动化覆盖使用固定数据/身份/AI替身，除明确标记“真实”的项目外均不代表外部服务验收。旧规格未勾选项不能简单视为未实现，也不能仅因有测试就全部勾选。

| 规格 | 已有覆盖/本轮证据 | 剩余边界 |
| --- | --- | --- |
| 001 Web控制台 | test_auth、test_pages、test_markets、test_engine_ledger、test_audit_tool；白名单、角色、CSRF、赛程、门槛、历史台账 | 未重新进行真实钉钉OAuth；旧版队列/自动纠错等范围不等同于后续人工审核流程；休眠/跨网络为环境依赖 |
| 002 UI | test_ui；本轮推荐审核与计划/复盘1440/375px Chrome | 不是当前真实身份/真实数据界面的全部交互认证 |
| 003 多入口登录 | test_auth中origin/state/Host/转发头、过期和单次使用回归 | 办公网172.16.37.247历史不可达，未新增网络验收；HTTP不等于TLS |
| 004 后台分析/回退 | test_analysis、test_analysis_providers；真实双CLI短探测 | 真实赛事单场两提供方超时；未证明全日长输入可完成 |
| 005 实时日志 | test_analysis_logs；本轮真实任务保存检索/心跳/超时事件 | 心跳不代表研究成功；未做长任务跨网络恢复的新实测 |
| 006 体系编辑 | test_systems：并发、冲突、恢复、快照、XSS/CSRF、viewer | 不为烟测编辑生产V6；本轮未重新进行生产保存 |
| 007 定时/复盘 | test_automation、test_reviews、test_ai_decisions；本轮隔离Chrome新增/启停/刷新/只读与复盘 | 未启用生产计划；未做真实赛果→真实AI复盘→生产台账验收 |
| 008 研究/审核/发布/复核/效果/通知 | test_research_workflow、test_recommendation_decisions、test_publications、test_monitoring、test_evaluation、test_notifications | 发布/通知仅隔离回归；无真实钉钉送达证明；证据/版本/效果等全部页面尚无本轮全覆盖浏览器认证 |
| 009 AI推理门禁 | test_ai_decisions、test_recommendation_decisions；本轮模拟AI理由可见、哈希、回退与审核；真实短探测 | 全量真实研究→推荐未完成；约1.18MB固定上下文仅证明程序容量，不是模型长输入能力认证；不宣称预测/收益能力 |

## 真实依赖探测

### 短结构化响应

产物：`var/functional-qa/probe-20261105T095545/`。

- Claude：succeeded，返回status=ok。
- Codex：succeeded，返回status=ok。
- 输入为公开的连通性短句，无赛事推荐、无网页工具调用、无发布。
- 未核实实际模型ID，不根据默认配置虚构模型身份。

### 官方来源和真实赛事工作流

隔离脚本：`var/functional-qa/live_workflow.py`。独立project和SQLite均在`var/functional-qa/`，未注册生产任务。

1. 首次两场子集尝试：官方当日清单只有1场足球/0篮球，按条件退出，不编比赛、不改销售状态。
2. 单场验收：`var/functional-qa/live-20261105T101615/results.json`。
   - 官方快照：2026-11-05 10:16:15/16 +08:00，均stale=false。
   - 场次：周四013，帕尔梅拉斯VS里莫，官方开赛2026-11-06 06:30。
   - 任务：`20261105T101616-2e2e194e2760`。
   - Claude：timeout，240.0秒。
   - Codex：timeout，240.0秒。公开事件末尾还记录上游过载与流断开重连；不能仅凭此推定所有超时的根因。
   - completed=0、failed=1；status=failed，未生成完整草稿、ai-decision或发布版本。
   - 这是**失败的真实验收**，不是成功推荐；正式功能仍需模型/网络可用时重新验收。

## 隔离Chrome交互验收

浏览器MCP连接失败，本轮复用独立本机Google Chrome/Playwright；没有绕过生产认证。两个脚本均启动临时HTTP应用、模拟身份/市场/AI返回，完成后关闭服务。

### 推荐与审核

脚本：`var/ai-decisions-qa/check_ui.py`，退出码0。

- 逐场研究→Claude模拟失败→Codex模拟结构化决策→草稿→审核页面。
- AI返回总结、理由、风险、撤销条件、提供方和哈希可见。
- `<script>`作为文本显示，未执行；JavaScript错误=[]。
- 1440px与375px均无横向溢出；已实际查看375px截图。
- 刷新审核通过；未点击发布。
- 结果：`var/ai-decisions-qa/results.json`；截图`decision-review-1440.png`、`decision-review-375.png`、`decision-rationale-375.png`。

### 定时与AI复盘

脚本：`var/automation-qa/check_ui.py`，退出码0。

- 临时计划保存、启停、刷新持久化；保存动作不调用模型。
- 复盘任务提交、AI模拟回退、结果安全展示、viewer只读。
- automation/reviews在1440px与375px无横溢，JavaScript错误=[]。
- 结果：`var/automation-qa/results.json`。

## 当前服务检查与部署阻塞

全量测试通过后尝试执行`rtk proxy deploy/restart.sh`，最终被工具权限门禁拒绝。**不将此前部署、当前旧进程健康或静态文件200当作本轮重启成功。**

只读检查：`var/functional-qa/health_smoke.py`，结果`var/functional-qa/health-results.json`：

- `/healthz` → 200，`{"ok":true}`。
- `/analysis`、`/automation`、`/reviews` → 302 `/login`。
- `/static/style.css`、`/static/analysis.js` → 200。

后续需在允许重启的用户会话中执行`rtk proxy deploy/restart.sh`，再复查健康/认证。恢复真实AI研究后，需要独立验证真实推荐决策和真实二串一；不得通过增大假数据、跳过研究或降低门槛补齐验收。
