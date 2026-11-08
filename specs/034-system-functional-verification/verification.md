# 验证记录

日期2026-11-08，执行于本机工作区。功能/路由/页面控制详情见[矩阵](functional-matrix.md)。

## 复现与修复

1. 红灯：100分字段与伪q/r字符串，在删除磁盘凭据后仍可发布审核。当前运行候选和发布均消费SourceProvenanceStore和独立覆盖层，核task/match/option/dimension/来源/管理员/时点；无凭据、hash篡改和错身份阻断。人工入口可保存已认证行动，显式新任务导入有效复核并重新AI取舍，不修改旧研究/票。
2. 红灯：浏览器取消排队任务已取消但toast为“任务状态格式无效”。控制响应不再误要求只在日志轮询存在的logs数组；实际手机继续提示“已继续分析”，取消提示正确。
3. 红灯：每日冻结台账pre撑宽文档。原文保留、局部横向滚动，桌面/手机document width复验不溢出。
4. 修复遗留报告未清洗Markdown HTML、首页重复汇总标题、已发布阶段仍标待审核、复盘等活动页Harness-only/Codex历史误标、日志缺主标题与人工复核表单默认排版。报告原文件不修改。新增非对象JSON反例从500转400，派生检查点剔除非schema字段。
5. 逐选项claim隔离后大量重复receipt使决策输入超限。决策投影按语义断言合并option引用、保留完整claims哈希和原始工件；不截断事实，不让AI验证receipt。正向测试迁移为实际研究→磁盘复核→新AI决策，不回退门禁。

## 自动化

- `.venv/bin/python -m pytest -q`：最终**521 passed in 200.59s**，源码冻结后执行。之前517/204.65s；收尾新增4项非对象JSON反例。更早514+1为旧Harness文案断言，已更新并重跑通过。
- `node tests/ui/common_controls.cjs`：实际app.js主题、防重提交、submitter保留、历史返回解锁通过。
- `.venv/bin/python -m compileall -q src` 与 `git diff --check` 通过。
- 专项覆盖缺盘、篡改review、跨task/option/dimension、非当前admin、无claim/错选项claim、原票不变、无receipt不得产生运行候选、合法session actor复核及新决策；见新增test_publication_provenance_gate / reviewed_reanalysis / legacy_report_safety。

## 浏览器

使用browser-use/browser-harness；最初生产已登录首页只读。用户浏览器失去CDP授权后改为独立无生产资料headless Chrome，9333只连接隔离5021服务；不是绕过生产登录。

- 1470×850与375×812，各21个页面/详情，最终42/42无JS error/rejection及文档溢出；包括有票/有研究/审核详情，不只空页。
- 实际点击：主题、手机导航/Escape、新建分析/取消、手机部分任务继续、日志提供方筛选/无结果搜索/跟随/下载、台账查询/重置、停用配置保存/计划添加、审核/确认发布（既有check幂等）、临场启动/取消、撤销、复盘启动、原文保存、复核后重新分析。
- viewer无admin按钮与导航、访问provenance403；匿名/退出/CSRF与权限由完整Flask集成测试覆盖。原生发布confirm经CDP确认；所有副作用只写临时DB/目录，未发消息、未执行生产发布或付费分析。
- 本机截图与DOM控制清单：`var/ui-qa/system-20261108/`；不提交真实私人日志或生产截图。渲染不是全按钮全状态点击的替代，上表明确余项。

## 部署

部署前生产analysis_runs/review_runs/recheck_runs的queued/running计数均0。最终`deploy/restart.sh`完成，launchd PID47446；`/healthz`返回ok，`/readiness`返回ready及db/policy均true。部署未改.env或原运行工件。

健康/就绪不证明官方网络、AI来源质量、可发布推荐或收益。今日真实全天与人工次日闭环仍归#4；生产逐页和跨地址OAuth归#8；真实研究依赖可靠性归#9；源端真实性/语义分组、数据安全、独立模型仍归#14。

## 交接

本轮代码和依赖的原有未提交claim schema/评分门禁/正向fixture一并收口；不纳入.env.example、生产ledger/runs/var或无关数据改动。提交关联#14/#8，推送当前main到origin/main，远程结果另行核验。
