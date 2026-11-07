# 019 运行日志错误修复

Issue #9；用户选择先只读诊断，后明确“按方案修复”。不配置巡检/监听，不中断已有分析，不扩权或安装Code Mode host。

## 需求与边界

1. 本机Codex0.155.1实际Help/features核对，受限子进程同时disable code_mode/code_mode_only/code_mode_prewarm/code_mode_host，保留shell/unified_exec/MCP/hooks/plugins等隔离；不修改用户全局配置。
2. stderr明确Code Mode host/未知feature配置错误时快速ProviderError(configuration)，清理进程组，本轮后续跳过不可用提供方，不每场重复超时；取消/清理失败不得再回退。
3. 仅逐场成功返回后的证据schema/来源语义校验失败每个provider允许最多一次同provider结构修复（Claude原始→Claude修复→必要时Codex原始→Codex修复，不递归），共享该provider原单场/总预算，保存原始失败及修复工件。不在程序补造source或verified，不降低70分；缺来源改unknown只能由实际AI返回后验证。
4. 原始调用超时/认证/限流/config失败不走结构修复；修复失败按原策略回退，所有失败和partial诚实保存，原成功检查点不覆盖。
5. UI/日志汇总错误代码和尝试，让用户区分Web健康/CLI存活/研究完成。测试mock，真实CLI仅有界无赛事最小返回探测，不冒报长研究完成。
6. 当前任务仍运行时不重启；测试后重新核对，结束后才部署。不启用自动修复/巡检/通知/投注。
