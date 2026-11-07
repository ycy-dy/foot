# 代码提交修改台账

建立日期：2026-11-06（北京时间）。用途：逐笔总结提交修改、验证边界与远程同步情况；不是业务推荐命中台账。

## 维护约定

1. 每次提交前新增唯一记录号，记录目的、变更范围、验证、未完成项、推送目标。
2. 提交完成后必须推送已配置上游；不使用force push。推送失败保留本地提交，向用户明确报告原因。
3. 当前条目以唯一记录号和提交说明定位；其提交哈希可用 `git log --all --grep=<记录号>` 查询，不为了写入自身哈希反复提交。
4. 提交前不能预先声称已推送；最终推送结果以Git返回、远程引用核验和当次答复为准，下次提交时可补记上一笔的哈希及结果。
5. 不记录密码、令牌或含凭证URL；只暂存明确范围，运行数据和其他工作区改动默认不混入。
6. 本台账自本次建立开始维护；之前提交只补记本轮已核实的一笔，不虚构完整历史。

## C20261106-001 · 项目整理、历史删除与旧体系停用

- **提交**：`919d63c` — `chore: remove legacy history and business policies`
- **作者**：yangcy（沿用仓库已有身份配置）。
- **变更目的**：保存此前未提交的应用源码与工程规格，执行用户确认的历史清理和旧业务体系移除。
- **范围**：源码、测试、工程文档、规格、依赖声明；历史目录已跟踪文件删除，旧体系正文/YAML删除、体系编辑页面删除，策略依赖操作停用；2,009个变更路径。
- **关键结果**：主页为体系待定义；新分析、续跑、审核发布及定时策略停用；运行工件和台账保留，不再用旧策略生成新推荐。
- **未提交内容**：环境模板改动、台账数据和运行产物；没有提交凭证、数据库或日志。
- **验证**：专项9项通过；暂存差异检查及基础凭证风险扫描通过；源码语法检查通过。全量中间版本159通过、28失败、35错误，旧测试未适配策略移除，另有既有台账数据依赖问题，不能宣称全绿。详见[移除验证记录](../specs/013-remove-business-policy/verification.md)。
- **部署记录**：现有服务重启及健康检查成功；不等于真实模型全链路验收。
- **推送目标**：`origin/master`。
- **同步结果**：建立本台账前已补推成功，远程从 `eec0b19` 更新至 `919d63c`；未强制推送。

## C20261106-002 · 提交后推送规范与修改台账

- **提交定位**：提交说明 `docs: add commit ledger and require remote push [C20261106-002]`；自身哈希通过Git查询。
- **变更目的**：落实用户“每次提交代码都推送远程，记录每次修改”的持续要求。
- **范围**：[Agent入口](../AGENTS.md)、本台账、[README入口](../README.md)。
- **关键结果**：默认提交后推送既有上游；推送失败不冒报成功；新增逐笔记录格式与自引用哈希处理约定。
- **验证**：文档链接与暂存差异检查；无运行时代码或配置更改，本笔不重复执行全量测试或重启服务。
- **已知边界**：上一笔全量旧套件兼容问题仍未修复；未把工作区其他数据改动纳入本笔。
- **推送目标**：`origin/master`。
- **同步结果**：`546fbc9` 已推送旧远程 `origin/master`，当次已核验远程与本地HEAD一致。

## C20261106-003 · GitHub远程与main分支迁移

- **提交定位**：`chore: migrate repository to GitHub main [C20261106-003]`。
- **目的**：用户要求将仓库改为 `https://github.com/ycy-dy/foot.git` 并使用 `main`。
- **范围**：README项目标题及仓库说明、AGENTS默认推送目标、本台账；Git本地配置改远程URL，分支master改名main。
- **历史处理**：保留现有提交历史，不删除.git、不创建假的first commit、不强推。旧提交中删除前的历史资料依然属于Git历史，迁移会一同推送；不将工作区未提交运行产物加入迁移提交。
- **检查**：目标 `git ls-remote` 成功且无引用（空仓库）；GitHub CLI当前未登录，后续Git推送仅尝试现有凭证助手。文档差异与链接检查，无运行时改动，不重启服务。
- **推送目标**：GitHub `origin/main`。
- **结果补记**：`e90c00c` 已在本地生成。先网络超时，后GitHub授权成功但推送被GH013密钥保护拒绝；旧提交网页存档含疑似第三方密钥，未绕过保护。此迁移链仅保留本地备份，不再推送。

## C20261106-004 · 当前源码干净历史首次提交

- **提交定位**：`first commit [C20261106-004]`，这是新main的根提交，无旧提交父节点。
- **授权**：用户获知GitHub密钥保护拦截后，明确选择“用当前已提交代码建立干净历史”，保留旧历史为本地备份分支。
- **范围**：以旧HEAD `e90c00c` 的已提交树为基础，仅更新本台账；不纳入未提交环境模板、台账数据、runs、var或凭证。
- **历史边界**：旧提交链保留本地 `backup/pre-clean-main-*` 分支，含被扫描命中的旧网页，绝不可推送该备份或使用 `--all`／`--mirror` 迁移。GitHub只推新的main。
- **验证**：创建前检查暂存区为空、根提交树与原HEAD仅台账不同；不重写工作区、不清除未提交数据；不绕过GitHub保护、不force push。源码未变，本次不重复测试或部署；旧套件失败边界仍见前述记录。
- **推送目标**：`origin/main`。
- **同步结果补记**：根提交 `a6c52c2` 已成功推送GitHub，origin/main建立，远程与本地一致。认证及密钥保护处理已补记 [Issue #2](https://github.com/ycy-dy/foot/issues/2)。

## C20261106-005 · 需求问题 Issue 与跨 Agent 交接规范

- **关联事项**：[Issue #1](https://github.com/ycy-dy/foot/issues/1)。
- **提交定位**：`docs: require issue tracking for agent handoffs [C20261106-005]`。
- **范围**：AGENTS持续规则、README导航/干净历史状态、Issue协作指南、GitHub统一Issue模板、本台账；不纳入其他工作区数据改动。
- **结果**：每个新需求/新问题创建或更新Issue，记录验收/决策/验证/提交/风险和下一步；全部完成才关闭，网络不可用如实标待同步，不泄露凭证。
- **验证**：Markdown本地链接、Issue模板YAML前置字段、暂存差异校验；远程Issue创建与读取；无运行时代码改动，不重跑全量或重启服务。旧测试兼容缺口不因本项完成而解决。
- **同步结果补记**：edc7e2b已推送并核验远程，Issue #1完成关闭。

## C20261106-006 · 70%证据推荐与每日冻结台账

- **关联**：[Issue #4](https://github.com/ycy-dy/foot/issues/4)、[规格014](../specs/014-evidence-gated-recommendations/spec.md)。
- **范围**：现行policy/评分契约、版本manifest、手动研究/AI取舍/审核发布链路、70%全栏目门槛、当日赛程主页与日台账、原票复盘关联、隔离测试迁移和工程入口；不恢复V6文件或history，不纳入原环境模板/运行台账/runs/var。
- **关键修复**：不能用条件推荐凑数；每腿独立可信证据达70；发布时重算证据时效、停售拦截；完整规则输入不使用日志长度截断；任务新建/复用返回契约一致。草稿含不成串原因、发布冻结原价/分支/分数/来源/AI与审核哈希。
- **验证/部署**：见[本轮验证记录](../specs/014-evidence-gated-recommendations/verification.md)，提交前补齐。独立模型未训练/校准，不承诺命中或收益，不自动投注/通知/计划。
- **提交定位**：`73aef16`，Refs #4。首次和一次限时重试push均网络超时，后续推送将一并同步；本地服务已部署，真实比赛全链路保持开放。

## C20261106-007 · 逐场分析入口与证据玩法明细

- **关联**：[Issue #5](https://github.com/ycy-dy/foot/issues/5)、[规格015](../specs/015-per-match-analysis/spec.md)。
- **范围**：首页每场分析链接、比赛详情只读AI研究摘要、精确身份/版本匹配projection、逐玩法证据分与理由风险撤销、管理员完整证据页评分、隔离测试与说明。
- **权限/边界**：viewer可读摘要不获得管理员研究日志入口，GET不运行AI不发布；无研究标待分析，旧版/低分不当当前推荐，冻结研究价与当前报价分开。不读取DWS或发送消息。
- **验证**：专项4项通过，全量/部署结果见[015验证](../specs/015-per-match-analysis/verification.md)。旧源/运行数据不改；提交后推送main，不推备份历史。
- **同步结果**：377c4ff已推送并核验远程一致，同时补推73aef16；Issue #5关闭。

## C20261106-008 · 梦想比分4串1独立栏目

- **关联**：[Issue #6](https://github.com/ycy-dy/foot/issues/6)、[规格016](../specs/016-dream-score-ticket/spec.md)。
- **范围**：首页独立梦想栏目/冻结发布投影、四腿比分赔率与组合乘积/证据分/理由风险撤销/台账入口；强化严格审核四腿唯一CRS、低分及比分价格一致性。
- **边界**：只显示当前政策审核发布版本，空态不凑单，不自动扩注、不投注；独立模型概率EV仍null，市场联合只是独立近似；不修改原票、生产数据和凭证。
- **验证**：见[016验证记录](../specs/016-dream-score-ticket/verification.md)；提交后push及结果由Issue/当次答复确认。
- **提交定位**：9efa552，Refs #6。此前push两次超时，远程当时377c4ff；后续推送本笔修复会一并补推。

## C20261107-009 · 修复重新分析按钮无响应

- **关联**：[Issue #7](https://github.com/ycy-dy/foot/issues/7)、[规格017](../specs/017-recompute-button/spec.md)。
- **根因/范围**：新版首页漏载analysis.js，按钮无span不满足render契约；修复script装配/button节点、null防护及提交失败持久反馈，增加管理员/viewer资源和API去重回归。
- **验证**：专项3 passed、node语法检查；全量部署见[017验证](../specs/017-recompute-button/verification.md)。测试不用生产CLI，不改推荐规则/原票/凭证。
- **同步结果**：23fb10d已推送并核验远程，同时补推9efa552，Issue #7/#6关闭。

## C20261107-010 · 全页面控制件验收与修复

- **关联**：[Issue #8](https://github.com/ycy-dy/foot/issues/8)、[规格018](../specs/018-ui-controls-audit/spec.md)、[页面控制矩阵](../specs/018-ui-controls-audit/control-matrix.md)。
- **范围**：分析状态日志健壮性/发布确认防重复，复盘临场轮询错误与终态、管理表单启用停用语义和CSRF/角色/转义、全站POST重复锁与返回解锁、资源版本一致、页面路由/权限矩阵及专项测试。
- **安全**：自动计划/持续监控/通知和测试发送没有授权仍禁用，保存停用正常；不触发生产AI、发布、通知，不改原票或运行数据。真实浏览器仅看到生产登录页，用户切换标签中断后停控，不绕过登录；其余隔离测试/真实脚本VM，边界如实列明。
- **验证**：见[018验证](../specs/018-ui-controls-audit/verification.md)，提交前补齐全量/部署。首轮2个旧测试仍预期全局409，迁移为CSRF400+启用403，不退化安全。
- **同步结果**：be8db5f已推送核验；部署代码原样再次全量297 passed/103.76s，Issue #8保留生产浏览器实际验收边界。

## C20261107-011 · CLI兼容与证据结构有界修复

- **关联**：[Issue #9](https://github.com/ycy-dy/foot/issues/9)、[规格019](../specs/019-runtime-provider-repair/spec.md)。用户明确按方案修复，不自动巡检/扩权/安装host。
- **范围**：Codex完整关闭code_mode系列隔离、stderr配置不兼容快速失败清理并本轮跳过；逐场每provider一次剩余预算内证据结构修复、脱敏原返回/attempt追踪，错误聚合提示；不造来源不降低70分。
- **验证**：受限Codex30秒无赛事最小JSON实际成功；专项20 passed，完整回归/部署见[019验证](../specs/019-runtime-provider-repair/verification.md)。原任务自然partial后才部署，不覆盖原检查点。
- **同步结果**：3a764bd已推送核验；后续真实研究仍Code Mode失败/超时，最小无工具探测不覆盖工具路径，已如实在Issue #9记录并继续修复。

## C20261107-012 · 有限网页研究与独立结构交付

- **关联**：[Issue #9](https://github.com/ycy-dy/foot/issues/9)、[规格020](../specs/020-bounded-research/spec.md)。
- **修复**：逐场排除工程AGENTS，专用Claude system prompt，有限3search/3fetch；工具call id去重；预留25%最多45s无工具AI整理公开证据，原schema验证才成功，未知仍不推荐；连续最终timeout两次停止保留。Codex native standalone_web_search在host/shell/MCP禁用下实测可用。
- **验证部署**：全量327 passed/107.02s，两提供方有界真实公开搜索返回JSON/URL；无active后重启5020 PID64617。见[020验证](../specs/020-bounded-research/verification.md)。未重跑整日真实赛事，不冒报70达标或模型性能。
- **同步结果**：62b7fda已push并核验远程。

## C20261107-013 · 本机精确OAuth回调配置

- **关联**：[Issue #10](https://github.com/ycy-dy/foot/issues/10)、[登录说明](loopback-login.md)。
- **处理**：用户确认127.0.0.1入口，本地.env追加精确loopback callback，保留原值；环境文件不提交，不含密钥/私有入口。无应用/机器人创建、不放开Host。
- **验证**：auth17 passed，空闲后重启PID80955；生产begin302至官方授权，callback精确匹配和state存在，真实扫码/官方服务端白名单待用户验证。
- **同步结果**：3bf4f67已推送，用户实际正常登录，Issue #10已关闭。

## C20261107-014 · DeepSeek Harness唯一AI执行

- **关联**：[Issue #11](https://github.com/ycy-dy/foot/issues/11)、[规格021](../specs/021-harness-provider/spec.md)。
- **范围**：dsh headless正式stdin/JSON adapter、项目只读web工具patch/no-tools整理、harness日志与最终工件验证、运行时单harness路由/无旧CLI回退、旧证据复用/manifest拒绝、页面与测试/配置/政策文案迁移；patch纳入package-data。
- **验证**：真实no-tools Harness JSON返回通过，真实web_search被调用但headless缺搜索API密钥、url null，明确未开通联网；不复制当前GUI凭证不假定同模型。完整回归/部署见[021验证](../specs/021-harness-provider/verification.md)。
- **安全**：禁用本地文件/shell/MCP相关工具/子代理/工作流/技能/插件，thinking不公开；不改原票/旧运行工件、不推备份分支。没有真实新比赛推荐或发送。
- **同步结果**：8eda872已推送并核验远程。

## C20261107-015 · pixmoving项目模型与安全凭据复用

- **关联**：[Issue #12](https://github.com/ycy-dy/foot/issues/12)、[规格022](../specs/022-pixmoving-model/spec.md)。
- **授权/范围**：用户选pixmoving/gpt-6.1-sol且授权项目headless通过官方credentials内部解析已保存引用；仅patch改模型/启credentials，不改全局默认/凭据，不使用聊天明文。patch纳入manifest代码hash，变更失效旧审核。
- **验证**：真实无工具小JSON ok；全量352 passed，manifest补充后专项/部署见[022验证](../specs/022-pixmoving-model/verification.md)。搜索授权独立不冒报联网，未发赛事/聊天数据验证。
- **安全提醒**：聊天中出现的凭据不存入代码、Issue、台账或命令，建议提供方撤销轮换；任何轮换由用户官方凭据界面处理。
- **同步结果**：8f81e3f已推送核验。

## C20261107-016 · Codex后台版本对齐诊断记录

- **关联**：[Issue #13](https://github.com/ycy-dy/foot/issues/13)、[处理说明](codex-daemon-version.md)。
- **授权处理**：用户分别同意restart和官方update --from-cli；后台从0.142.0对齐本机0.167.0，使用本机包，无下载、不清配置/历史、不关闭信任。
- **验证**：官方version三版本一致；PTY启动10秒保持运行无原错误，用户终端交互仍待确认；proxy无输出/超时未冒报成功。当前其他Codex替代迁移代码仍待收口，不纳入本记录提交。
- **同步结果**：25a2ba7已推送并核验远程；Issue #13等待用户确认后关闭。

## C20261107-017 · 搜索不可用时Codex CLI替代

- **关联**：[Issue #11](https://github.com/ycy-dy/foot/issues/11)、[规格023](../specs/023-search-codex-fallback/spec.md)。
- **范围**：用户授权Harness搜索无正式凭据时改用当前唯一Codex CLI；更新policy/runtime路由/工件版本门禁/测试迁移，保留Harness显式切换但不混合；修复codex响应工件复制和新版官方npm入口。
- **验证**：Lead最终全量360 passed/104.52s；Codex0.167.0 native搜索实测返回官方URL但伴Code Mode host警告，禁host/shell/MCP未绕过；无active后服务PID23567健康。详见023验证。真实赛事、70分和盈利仍待新任务验收。
- **提交定位**：`feat: use Codex CLI when Harness search unavailable [C20261107-017]`，Refs #11；目标origin/main，push结果后补。


