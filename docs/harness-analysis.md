# DeepSeek Harness 分析执行

用户要求分析/重新分析不再调用Claude/Codex。现行规格021，运行时只调用本机 `dsh headless --json -`，独立Session。无需打开当前GUI让Agent模拟点击；不传当前Session ID，不声称使用本对话相同模型。

## 执行与日志

研究→证据JSON→确定性评分/候选→Harness最终取舍→审核与管理员发布→日台账/复盘。提供方标识harness；只有final.text通过JSON schema及业务校验才成功。thinking事件不显示，原始最终返回/输入/提供方与哈希保留。

研究使用项目只读patch，禁本地shell/文件/技能/子代理/工作流/插件管理，公开web可用时才检索；整理阶段无工具。不启用计划、通知、投注。不回退旧CLI，旧工件只读历史。

## 本机配置状态

真实headless无工具JSON探测成功。真实web_search被调用，但当前headless搜索缺可用API密钥，因此无法认定联网赛事研究可用。需要用户在官方headless profile支持的凭证/搜索配置中授权；不要在聊天、Issue、代码或shell命令回显中粘贴密钥。模型/API额度由headless自身配置决定，不自动等于当前Desktop配置；本次不复制或改用户全局凭证。

缺工具/额度/认证时应显示失败或证据缺口，不将unknown模板当研究成果/70达标推荐。分析按钮链路可执行不代表外部搜索已开通；真实赛事仍需进一步验收。

旧工作流runtime_provider或规则/代码版本不匹配时不能续跑为当前成功；请从首页启动新任务，不自动恢复旧CLI结果。
