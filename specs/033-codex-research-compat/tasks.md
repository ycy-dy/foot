# 任务

- [x] 定位现有任务两次configuration停止，确认不是超时/70分否决。
- [x] 启动诊断后有效返回的红灯测试，以及真实失败阻断对照。
- [x] 实现当前Codex协议，删除旧Claude解析和动作别名，保留工具白名单和预算。
- [x] 完整证据schema单场真实有界验收：公开采集+Codex无工具研究，23维/2来源，84.21秒。
- [x] 聚焦与全量测试：最终499 passed/157.06秒，编译和差异通过。
- [x] 部署健康：PID69183，/healthz ok、/readiness db/policy=true。
- [x] Issue总结、提交推送：3eab6e2已到origin/main且远程哈希一致；已提交源码独立回归502 passed。
