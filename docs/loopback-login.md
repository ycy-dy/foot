# 本机登录入口回调修复

2026-11-07，Issue #10。用户使用 http://127.0.0.1:5020，原环境仅有网络入口callback，begin精确allowlist正确拒绝但交付入口与配置不一致。

本机环境只追加 http://127.0.0.1:5020/auth/dingtalk/callback，保留已有入口，配置权限600。未放开任意Host、未创建应用或机器人，密钥和私有配置不进Git。

验证：认证专项17 passed/0.38s；active分析为空后现有restart成功PID80955，健康通过。生产begin返回302至login.dingtalk.com，redirect_uri精确loopback，state存在（未打印内容）。这证明本项目入口通过，不代表钉钉服务端已允许该地址或真实扫码已完成。

若官方授权页报redirect_uri不合法，请由现有应用的授权管理员在开发者平台该应用的回调URL配置中添加以上精确地址；不新建应用、不更换身份、不绕过企业限制。localhost与127.0.0.1是不同来源，使用哪个必须精确配置哪个；不能把全部请求Host反射为可信回调。

当前请重新打开本机地址并点击钉钉登录。真实扫码由用户完成，不在Issue或日志记录密码/token/授权code/state。
