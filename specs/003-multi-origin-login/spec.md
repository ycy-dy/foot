# Feature Specification: 多网络入口钉钉登录

**Created**: 2026-11-04 | **Status**: Implemented（LAN/Tailscale 已观察到真实登录；办公网待网络恢复验收）
**Input**: 用户要求以下三个入口均可访问和登录（重复地址去重）：

- `http://192.168.1.4:5020/auth/dingtalk/callback`
- `http://100.73.136.41:5020/auth/dingtalk/callback`
- `http://172.16.37.247:5020/auth/dingtalk/callback`

## 验收

- 授权请求使用与当前访问入口同源且明确配置的回调地址，不固定跳转到另一网络。
- 回调地址使用配置白名单，不信任任意 Host 或 X-Forwarded-Host。
- OAuth state、时效、单次消费、企业成员、白名单、角色与 CSRF 校验保持有效。
- 会话绑定发起时的回调来源，跨入口不会错误复用 state；每个 IP 独立登录。
- 保留原单地址配置兼容性，增加多地址配置并写明钉钉后台同步要求。
- 分别验证本机网络可达性、授权 URL 和模拟完整回调；真实身份确认由用户完成，不把 HTTP 可达当作登录验收。
- 无法路由到未配置在本机的历史地址时，如实注明网络限制，不擅自增加网卡别名。
