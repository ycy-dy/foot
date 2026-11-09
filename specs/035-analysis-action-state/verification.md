# Verification

2026-11-09，Issue #8。原始反例命令`.venv/bin/python -m pytest tests/test_recompute_ui.py -q`为2 failed/2 passed，证实无任务固定重新分析与跨日任务混入。

## 原因与实现

模板初始文案、真实analysis.js终态分支都写死“重新分析”；Store.latest_analysis使用global-active OR business_date，把展示和准入混用。已实现同业务日查询、独立active查询/恢复、并发唯一索引不变；跨日新建/跨任务续跑409，不冒称当天已分析或继续成功。

统一analysis_action契约（mode/label/disabled/title），共用模板与任务API/JS消费同一结果：无记录开始、排队等待、执行中提供方、取消中终止、有尝试或成功重新、未执行取消开始、未启动失败重试。所有同日历史会参与判断；新排队取消不抹去此前真实尝试。未有检查点不显示可续跑，未执行取消不称保留了检查点。开始使用本地Lucide play图标，更新analysis.js版本为8。

## 验证

- 最终完整`.venv/bin/python -m pytest -q`：**539 passed in 146.19s**；上一轮539/144.01s。
- 表驱动覆盖queued/running/succeeded/partial/failed/cancelled/interrupted、空attempts/已有尝试、同日历史、跨日新建、死worker、跨任务resume、权限/CSRF/同日去重。
- Node运行真实analysis.js，不仅检查字符串：首次初始、提交锁/queued、未执行取消/恢复开始、跨日409保留开始/错误提示。
- browser-use隔离5021/假身份/本地DB/无worker调用，1470×850和375×812实际点击开始→等待（禁用）→取消→开始；已有研究日期重新分析。手机document宽375=scrollWidth375，无溢出。截图在`var/ui-qa/analysis-action-20261109/`，不提交私人生产截图。
- 正式已登录5020首页只读复验：日期2026-11-09，button=开始分析，mode=start，task=null，未在生产触发AI或更改票/发布。
- `node --check src/foot_web/static/analysis.js`、compileall和diff检查通过。

## 部署和边界

部署前analysis/review/recheck queued/running均0；最终`deploy/restart.sh`运行PID48678，healthz ok/readiness db+policy true。开发期旧进程加载新模板曾出现analysis_action undefined，已在专项通过后重启恢复；最终生产页面已核。

不修改现行提供方、评分、推荐规则或原任务/票据；原env/ledger/runs改动保留不入本次提交。完整赛事真实闭环与其他生产UI剩余范围仍归原Issues，不能因本次按钮修复关闭整个#8。
