# 028 验证

2026-11-07：补充安全响应头（CSP、Permissions-Policy）和Secure Cookie显式配置FOOT_SECURE_COOKIE；HTTP本机默认不强制Secure避免登录失效，HTTPS环境可设置1。安全认证专项19 passed，完整回归365 passed/103.76s。

OAuth callback仍使用钉钉要求的GET code/state，但应用不将参数写业务事件；公网部署需TLS反向代理/访问日志脱敏、限流和集中审计，未在本轮直接改变部署拓扑。
