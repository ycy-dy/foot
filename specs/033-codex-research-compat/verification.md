# 033 验证记录

日期：2026-11-08，Issue #9。当前Codex CLI 0.167.0；以对应官方exec_events与WebSearchAction定义核对协议。

## 已验证

- 红灯：启动host诊断后有效返回被旧逻辑终止；turn.failed加响应文件被误接受；新增回归先4失败，再修复。
- 当前Codex JSONL：thread/turn/item事件，item.error非致命；error/turn.failed终止；search/open_page/find_in_page精确动作，other只作未决开始占位，缺动作终态/未知/旧别名/越权拒绝。终态不存在不能仅凭响应文件成功。
- 删除Claude执行、流式、包装返回和Markdown剥壳旧解析；Harness仅保留显式独立协议，policy仍唯一codex，无静默混合。
- 本机目录实测gpt-6-astra tool_mode=code_mode_only。临时direct工具模式保留模型身份，不改全局配置、不安装/启用host/shell/MCP。
- 原网关搜索实测POST /alpha/search返回404；host修复不等于搜索能力。原生搜索预检实验已移除，不能把empty sources当研究成功。
- 新资料通路：agent-reach/Exa一搜索、至多两正文，采集deadline/取消/子进程清理；独立receipt保留原始返回/哈希，输入只去重复公开内容。Codex无工具完成真实研究，最终取舍/归因禁用工具，临场资料亦先独立采集。
- 真实完整单场：`runs/2026-11-08/20261108T115718-codex-compat-probe/`，23维、2来源，schema及证据校验通过，总84.21秒。伤停冲突/缺少时点如实记录，不编造70分/推荐；没有人工确认、发布或投注。早期多次失败/空来源/超时探测保留，不覆盖。
- 原xhigh整理曾144秒无交付，改证据整理low推理强度+去重复材料后84.21秒交付；仅一次计时，不是SLO保证，最终推荐门槛未降低。
- 决策输入重复每选项评分明细导致2MB边界，改为每选项只传版本/分数/准入，逐场完整证据保留，不截断候选；真实发布fixture复验通过。
- 最终完整回归：`499 passed in 157.06s`。聚焦解析/预算/研究81 passed（后续新增/移除以全量为准）。compileall与git diff --check通过。
- 最后日志回调None/安全URL反例补强后再次完整回归：**503 passed in 152.25s**；临场/研究/决策专项31 passed。最终源码冻结后无skip/xfail。

## 真实与模拟边界

真实单场不是全业务日AI取舍/审核发布/次日复盘，也不证明来源内容正确、70分命中或盈利。官方网关原生搜索404仍未修复，运行已明确改用现有公开资料工具，不伪装Codex原生搜索成功。正文/摘要和人工复核分层，来源凭据强制消费风险由Issue #14保留。

完整回归早期出现重复上下文超限，以及测试期间改源码引发manifest版本拒绝；最终冻结源码后全量通过，没有放宽版本检查或skip测试。

## 部署

全量通过后确认active=0，deploy/restart.sh成功；最后部署PID69183，/healthz返回ok，/readiness返回db/policy=true；launchd缩减PATH下mcporter0.12.4可执行。旧失败任务保持失败，版本更新后需新建任务。未自动启动全业务日或发布，实际资料/原AI工件未入Git。
