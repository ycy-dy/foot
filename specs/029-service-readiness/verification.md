# 029 运维就绪与CSP收口

公开/readiness检查数据库核心表与policy，使用只读SQLite（timeout250ms）、缺库不创建、空库503、政策错误不泄露；不触发CLI/网络/业务动作。healthz仍为liveness，不能当分析质量认证。

发现前轮CSP script-src self会阻断已存在内联FOOT.csrf/主题/发布确认，改为每请求nonce，仅授权已知脚本，不开script unsafe-inline。nonce与HTML匹配及每请求不同有测试。

- 就绪/CSP/按钮专项13 passed；完整回归372 passed/104.22s。
- 无active分析后现有restart成功，5020 PID40124；真实/readiness返回200 JSON ready/db/policy=true，不再把登录页200当成功。/login CSP nonce与HTML实测匹配。
- 独立复核指出前轮发布audit source层级有误（误指check envelope），已修为official_source并加真实发布工件哈希/顶层football,basketball断言；发布/就绪/CSP合计8 passed/6.35s。随后最终全量372 passed/100.74s，空闲再次restart PID42774健康，交付本轮修复。

仍未实现的完整证据provenance、冻结baseline评估、stable ID缺失/碰撞、全局TLS/限流/集中metrics均不能由readiness true推断达标。
