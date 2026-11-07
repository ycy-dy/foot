# Tasks

- [x] O001 区分liveness/readiness，新增公开只读依赖检查，缺库不创建/空库拒绝/错误脱敏。
- [x] O002 补齐readiness正反测试；修复前轮CSP阻断已知内联初始化，通过每请求nonce而非unsafe-inline授权。
- [x] O003 就绪/CSP/按钮专项13 passed，新增nonce每请求不同和全部已知内联脚本一致性测试。
- [x] O004 最终全量372 passed/100.74s，无active后重启PID42774；readiness真实JSON及CSP nonce匹配已验证。
- [x] O005 Issue/台账及未实现边界随提交，push实际结果后核验；完整目标保持开放。
