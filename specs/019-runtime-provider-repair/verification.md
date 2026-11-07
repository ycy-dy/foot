# 019 验证记录

2026-11-07，Issue #9，用户确认修复。未配置持续巡检，未安装host或改全局Codex配置，未降低证据门槛。

- 本机codex-cli 0.155.1 exec --help/features实际核对。加入code_mode/code_mode_only/code_mode_prewarm与host共同禁用，维持shell/unified_exec/MCP/浏览器/hooks等隔离。
- stderr确定性配置不兼容立即ProviderError(configuration)，进程组清理，workflow本轮跳过该provider；不等待每场180秒。分块stderr用有界tail识别。
- 真实最小探测：30秒上限、临时目录、无赛事数据/不读本地文件/不调用工具的JSON schema，返回{'ok':true}。只证明基本调用，无长研究成功证明。
- 每provider原调用返回后validate_evidence失败才一次repair，和原调用共享deadline及全轮预算；失败回退，取消/清理失败立停，超时/认证/config不修复。不在Python补造source/verified。原返回、失败和修复attempt不可覆盖，脱敏key/value，超2MB不截断。
- 错误聚合只按provider/code/count给提示，不暴露prompt或原返回；任务页展示，不将心跳当成功。
- 专项20 passed/1.21s。首次全量316 passed/1 failed：旧篡改测试用第一个JSON当checkpoint，现在新增response/attempt工件后误取；已改按payload定位真实checkpoint，保留篡改拒绝测试。
- 原生产任务09:19:29自然partial，未主动取消/重启打断；旧失败原票/检查点不改写。

最终完整回归317 passed/104.84s、退出0。部署前只读查询确认active analysis为空，原任务partial保持不变；现有restart.sh成功，5020 PID42121，healthz ok，实际调用code_mode系列均禁用。未在部署后自动发起新的真实赛事任务，真实长研究改善仍需新返回；不会冒报已完成赛事推荐。git diff --check通过。
