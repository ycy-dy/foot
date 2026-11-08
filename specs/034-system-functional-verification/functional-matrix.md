# 全功能、逻辑与控制件矩阵

2026-11-08，Issue #14 / #8。49条生产路由规则（不含HEAD/OPTIONS和临时QA登录路由）；页面按实际活动路由计，不把保留但未挂载模板当可用功能。

## 状态口径

- 自动测试：运行实际应用/服务/工件或脚本，外部官方接口、身份、AI和发送使用隔离double；不证明线上来源或模型准确率。
- 浏览器渲染：1470×850、375×812各21个页面/详情，共42次，无JS异常及文档横向溢出；截图在本机`var/ui-qa/system-20261108/`。
- 浏览器点击：下面明确标明已点击的控制；其余只列自动测试，不冒称每一个状态都已人工浏览器验收。
- 生产只读：已认证首页曾打开；完整生产逐页、跨地址OAuth及真实全天→人工发布→次日复盘仍待验，不为测试触发生产付费任务或消息。

## 核心逻辑

| 模块 | 实际逻辑与边界 | 验证 |
| --- | --- | --- |
| 官方输入 | 足球/篮球完整业务日、稳定身份、足球时间窗口、篮球客前主后、快照sha/双时钟/坏快照恢复 | test_markets / official_identity / fetcher_snapshots / pages |
| 政策版本 | 唯一当前policy提供方Codex；规则/schema/代码哈希冻结，变更阻止复用与发布，不调用Claude或隐式回退 | provider_selection / harness_routing / policy_removed / publications |
| AI研究 | 价格盲输入、23维、失败路径、3次搜索/3篇预算、公开采集与AI判断分层、严格当前协议、超时/清理/取消 | public_research / bounded_provider_tools / provider_compatibility / research_stages / evidence_repair |
| 任务状态 | 排队→运行→部分/失败/取消/成功；全局单任务准入；只续未完成场；死worker恢复；成功检查点不可覆盖 | analysis / research_workflow / task_actions |
| 凭据准入 | 原文/quote/review磁盘哈希、task/match/option/dimension/URL/时点/当前admin白名单；伪字符串不产生运行候选 | source_provenance / publication_provenance_gate / reviewed_reanalysis |
| 人工复核回流 | 登录actor与服务器时点，独立覆盖层；显式新任务刷新官方价格，受限资料复用并重新AI取舍；原研究和原票不改 | provenance_ui / reviewed_reanalysis |
| 评分 | 11固定非赔率权重、所有23维conflict否决、70分、关键维度48小时、独立来源组、选项依据；不补造概率/EV | evidence_confidence / evidence_confidence_all_conflicts |
| 候选/决策 | 分段独立、不补腿、六类/八结构、Decimal全中奖分支成本门禁、梦想4场路径；AI完整slot选择与风险否决 | recommendation_decisions / audit_tool / dream_ticket / daily_ledger |
| 发布 | 校验AI原始返回/上下文/检查点、当前磁盘凭据、刷新官方销售与完整市场、真实独立审核脚本、冻结baseline；确认后原子推广/幂等 | publications / frozen_baseline / publication_provenance_gate |
| 临场 | 对照原票查变价/停售/开赛/阵容，独立记录变化，不自动替换或撤销票；取消清理 | monitoring / publications / management_controls |
| 复盘 | 锁原票、官方身份/终场/半场、主队让分、复合分支Decimal、取消/待定、AI解释另版；失败不替换成功，重复不双计 | reviews / ai_decisions / task_actions / engine_ledger |
| 台账/评估 | 最终/六类/结构/梦想分账；待赛不进分母；实际收支null；只读冻结baseline，缺失明确gap | daily_ledger / frozen_baseline / evaluation / engine_ledger |
| 安全/运维 | admin/viewer/匿名、CSRF、OAuth state/同源、CSP nonce、内容清洗、只读readiness；自动执行/通知硬停用 | auth / security_headers / readiness / management_controls / legacy_report_safety |

## 页面与全部控制族

所有下面页面均已浏览器桌面/手机渲染，动态复盘/临场页另有任务状态截图。导航链接逐项检查目标注册，写操作均测试admin/viewer和CSRF。

| 页面 | 控制件与行为 | 自动测试与实际点击 |
| --- | --- | --- |
| 全站 | 左侧导航、手机菜单、Escape、主题、退出、跳至内容 | auth/ui/page_control_matrix；主题、手机展开/Escape已点；退出自动测试 |
| 登录/拒绝 | 钉钉入口、回调、白名单、同源选择、拒绝与会话过期 | auth/security_headers；真实企业授权不代操作 |
| 首页 `/` | 业务日、重新分析、两处终止、复用checkbox、任务/台账/逐场链接 | recompute_ui/task_actions；新建与终止已点，终止toast已复验；日期/复用后端测试 |
| 分析列表 `/analysis` | 任务链接、状态/提供方 | page_control_matrix/analysis；列表渲染与链接注册 |
| 任务详情 | 新建、取消、继续、逐场进度、日志折叠、全部/Codex/Harness历史/系统、搜索、跟随、最新、下载 | analysis_controls/logs/research_workflow；手机继续、Codex过滤、无匹配搜索、跟随与下载已点；最新自动/JS测试，非本轮逐状态点击 |
| 逐场详情（足球/篮球） | 市场表、研究摘要、详情折叠、研究任务/完整证据链接 | match_analysis/pages；双队序/无研究/旧版/失败状态自动测试 |
| 完整证据 | 23维、来源锚点、来源外链、选项意见折叠、实时凭据评分、返回 | research_workflow/match_analysis/provenance；页面渲染，外链不全部访问 |
| 审核发布 | 刷新审核、工件/脚本折叠、确认checkbox、发布原生confirm、防重提交 | publications/analysis_controls；审核、勾选、confirm和发布已点，返回既有check版本幂等 |
| 发布详情 | 版本变化折叠、原票报告、首发checkbox、临场复核、原因输入/撤销 | publications/monitoring；临场启动、取消、撤销已点，撤销后原文保留/按钮隐藏 |
| 每日台账 | 日期查询、冻结原票/details/哈希、无票/撤销版本 | daily_ledger；双视口原票局部滚动及日期查询已实际复验 |
| 历史推荐 | 日期/历史日期链接、复盘并更新、任务进度/成功刷新、原票与当前版本 | task_actions/reviews；选定业务日和不改原票集成测试；复盘列表启动已点 |
| 台账查询 | 起止日、栏目、类别、状态、关键词、含替代、查询/重置、历史链接 | engine_ledger/page_control_matrix；关键词无结果查询和重置已点 |
| 命中率 | 月份/全部chip、历史日期链接、分类/逐日统计 | ui/engine_ledger；浏览器渲染，筛选自动测试 |
| 分析效果 | 月份/栏目/单位/球种select、查询、gap/空态 | evaluation/frozen_baseline；单腿切换/查询已点，其他参数正反测试 |
| 完整报告 | 已发布报告/缺报告404、只读清洗输出 | pages/legacy_report_safety；已发布渲染，恶意legacy HTML回归 |
| 复盘列表/详情 | 日期、开始、任务链接、日志/轮询、返回历史/台账/统计 | reviews/management_controls/ai_decisions；启动与排队页已点，完整结算→AI成功由集成测试 |
| 定时分析 | 名称/类型/时间/offset、添加/编辑保存、禁用启用、details | automation/management_controls；停用计划添加已点，编辑/非法输入自动测试，不能启用 |
| 临场监控 | lead/interval、首发checkbox、保存停用、任务链接 | monitoring/management_controls；保存已点、范围/伪造启用拒绝自动测试 |
| 临场任务 | 原发布、取消、状态日志/详情 | management_controls/monitoring；排队取消已点，运行取消/清理自动测试 |
| 钉钉提醒 | origin选择、保存停用、启用/测试发送禁用、记录 | notifications/management_controls；保存已点、无enqueue测试，不发送消息 |
| 人工证据复核 | URL/原文保存、task/claim/确认、记录复核、新task重新分析 | provenance_ui/reviewed_reanalysis；原文保存与重新分析已点，合法复核/错误绑定/actor由实际Flask集成测试 |
| 执行版本 | 规则检查、当前provider/哈希 | provider_selection/page_control_matrix；双视口只读 |
| 操作日志 | 最近100条、表格滚动 | auth/ui；admin可读/viewer403，不公开日志数据 |

## 路由登记（49条规则）

| 方法 | 路径 | 责任/测试 |
| --- | --- | --- |
| GET | `/static/<path:filename>` | 静态资源/ui |
| GET/POST（2规则） | `/automation` | 计划/automation |
| GET/POST（2规则） | `/reviews` | 列表与启动/reviews |
| GET | `/reviews/<task_id>` | 复盘详情/ai_decisions |
| GET | `/api/reviews/<task_id>` | 状态日志/management_controls |
| GET | `/login`、`/auth/dingtalk/begin`、`/auth/dingtalk/callback`、`/denied`（4规则） | auth |
| POST | `/logout` | auth |
| GET | `/healthz`、`/readiness`（2规则） | readiness |
| GET | `/`、`/daily-ledger`（2规则） | pages/daily_ledger |
| POST | `/api/recompute` | recompute_ui/analysis |
| GET | `/api/analysis/<task_id>`、`/api/analysis/<task_id>/logs`、`/api/analysis/<task_id>/logs/download`（3规则） | analysis/logs |
| GET | `/analysis/<task_id>`、`/match/<sport>/<num>`（2规则） | analysis/match_analysis |
| GET | `/ledger`、`/history`、`/stats`、`/report`（4规则） | pages/engine_ledger/reports |
| GET | `/api/today`、`/api/stats`、`/admin/events`（3规则） | pages/auth |
| GET | `/analysis` | research/page_control_matrix |
| POST | `/api/analysis/<task_id>/<action>` | cancel/resume/research_workflow |
| GET | `/api/analysis/<task_id>/matches`、`/analysis/<task_id>/matches/<match_id>`（2规则） | research_workflow |
| GET | `/research/versions` | provider_selection |
| GET/POST（2规则） | `/analysis/<task_id>/review` | publications |
| GET | `/publications/<publication_id>` | publications |
| GET+POST（1规则） | `/provenance` | provenance_ui/reviewed_reanalysis |
| GET | `/research/evaluation` | evaluation |
| GET/POST（2规则） | `/research/monitoring` | monitoring |
| POST | `/publications/<publication_id>/recheck`、`/publications/<publication_id>/withdraw`（2规则） | monitoring/publications |
| GET | `/rechecks/<task_id>` | monitoring |
| POST | `/rechecks/<task_id>/cancel` | management_controls |
| GET | `/api/rechecks/<task_id>` | management_controls |
| GET/POST（2规则） | `/research/notifications` | notifications |
| POST | `/research/notifications/test` | notifications/management_controls（403停用） |

## 未完成与非功能项

1. 真实全天赛事研究→合格候选→人工发布→次日官方结果复盘，仍由Issue #4验收，不为覆盖按钮伪造生产receipt。
2. 外部Exa来源真实性/语义支持、全域OAuth/网络和生产逐页检查、CLI未来版本及故障率，仍分别由#9/#8跟进；健康200不等于这些能力有效。
3. 独立预测模型、时间外校准、CI/盈利验证未部署，概率和EV继续null；不是页面缺陷，不编造实现。
4. 自动计划/通知/持续监控按当前授权停用；配置保存不是启用或投递成功。
5. 本轮没有声称所有按钮在所有状态/所有生产账号均已点击；上表保留自动测试与真实点击差别，完整生产验收Issue保持开放。
