# Codex config/read启动错误处理

2026-11-07，Issue #13。用户终端报告config/read failed while checking remote project trust。

只读doctor：CLI0.167.0，后台0.142.0，TOML正常且项目trusted。经用户确认先daemon restart，仍旧固定包；再次取得明确授权，执行官方codex app-server daemon update --from-cli --yes，用本机已安装CLI包复制固定后台，不下载、不清空凭据/历史、不关闭信任检查。

结果daemon version显示CLI/受管包/运行后台均0.167.0。PTY运行codex --no-alt-screen观察10秒保持运行，无原信任错误、无Error/panic；未输入任务，未触发模型调用。直接proxy JSON-RPC探测一次超时、一次无输出，不作为config/read成功证据。需用户原终端确认正常交互，不能仅靠版本匹配宣布全通过。

后台包现固定到本地CLI版本。以后CLI升级若再次版本漂移，可先doctor/version核实，再经确认用官方update --from-cli对齐；不要直接删配置/信任或升级到未确认版本。其他doctor可选MCP路径警告未擅自清理。
