# 验证结果

2026-11-07，Issue #9。用户要求解决新增研究0的实际缺陷。

- 原观察任务已由管理员取消，5条仅缓存成功、无新返回；观察job终态退出，未擅自取消或重复启动。
- Codex受限35秒真实公开网页搜索探测：启用standalone_web_search，保持code_mode/host/shell/MCP禁用，返回官方GitHub URL，退出0且无host错误。无工具最小探测不能替代这次结果。
- Claude真实30秒至多一次搜索探测返回结构JSON及真实URL。初次budget探测发现同tool call流式/完整事件重复计数，已按工具id去重并增加自动测试。公开tool_result与assistant输出仅用于禁工具整理，不采私有推理；超限fail closed，不截断补造。
- 两阶段及原repair兼容专项、provider隔离、预算/取消/无公开证据/连续超时测试保留；旧测试调整为25%预留预算及evidence_structure阶段，未弱化deadline。
- 最终全量327 passed/107.02s，退出0；git diff --check通过。
- 部署前确认active analysis为空；现有restart成功，5020 PID64617健康通过。

尚未重新启动整日24场真实研究，不能声明所有真实赛事已分析成功或达到70证据分。已验证两种CLI有限公开检索可交付，不等于比分模型训练或收益认证；无来源仍unknown、无达标仍不推荐。未启用巡检/通知/投注，旧原票与检查点不覆盖。
