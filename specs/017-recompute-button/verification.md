# 017 验证

2026-11-07，Issue #7。

- 根因：首页新版模板未加载analysis.js；按钮无span导致render空引用。已修复模板脚本/节点，JS容错，提交失败固定显示在状态区，不只短toast；继续防重/CSRF/管理员授权。
- 专项3 passed/0.11s：管理员资源和按钮DOM、viewer无控制器、隔离launcher双请求只新建一次任务且reused正确。
- node --check通过。Node vm模拟DOM运行真实analysis.js：绑定点击、双击仅一fetch、503失败toast及持久状态显示，通过；非浏览器视觉验收、不调用生产CLI。
- 初始测试导入bs4不可用，已改内置HTMLParser，没有安装依赖。
- 最终全量246 passed/100.87s，退出0；git diff --check通过。
- 未实际触发生产赛事AI任务/通知/投注，真实长任务状态仍由用户操作后的真实返回判定，不把按钮修复当模型预测认证。

现有deploy/restart.sh成功，端口5020 PID8831；healthz返回ok=true，实际/static/analysis.js?v=6包含新null防护与持久错误提示。未进行生产登录后浏览器完整点击（避免启动真实重复任务），隔离API及JS运行模拟已验证。
