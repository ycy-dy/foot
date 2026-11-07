# 021 DeepSeek Harness 唯一分析提供方

用户明确要求点击分析/重新分析不再调用Claude或Codex Agent，直接使用DeepSeek Harness。Issue #11。

## 实施契约

- 本机dsh --help及headless --help核实正式入口：dsh headless --json -，stdin输入，独立Session，不采用当前会话ID；只读取官方最终final.text并校验原JSON schema，不把text/思考/启动成功当分析完成。
- 研究/最终取舍/复盘及临场AI统一harness唯一路由；失败保持失败，不自动回退Claude/Codex，不接受其新成功工件。原历史可读但新manifest runtime_provider=harness，旧代码/提供方检查点不可冒充新研究复用。
- 项目专用patch覆盖headless：read-only sandbox，禁止bash/pwsh/文件/技能/子代理/工作流/目标/插件管理等工具，只保留公开web；no-tools整理关闭web。权限保守，不修改全局profile/凭证。任何非白名单tool_call拒绝继续。
- thinking事件不写公开日志；status/tool/final结构化解析，final无截断。保存harness.response.json及原有哈希/尝试，不伪造模型身份，model未知None。
- 沿用014/020证据>=70、有限研究/无工具整理、确定性审核、日台账/人工发布，不投注、不自动通知或开启计划。

## 验收

离线路由保证所有generator调用为harness且无旧CLI回退；拒绝CLI冒充/旧manifest、真实小无工具JSON与有界公开web探测，测试按钮/API/日志/provider显示、完整回归后空闲部署。真实账户模型额度/代理配置在独立headless profile按用户已有配置运行，不宣称自动继承当前GUI模型或额度；缺配置如实失败。
