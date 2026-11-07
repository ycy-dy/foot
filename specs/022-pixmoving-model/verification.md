# pixmoving配置验证

2026-11-07，Issue #12。用户选择pixmoving/gpt-6.1-sol并明确授权官方凭据服务内部复用已保存引用，不读取显示密钥。

- route实际存在，api=openai-completions，baseURL与用户指定一致，模型目录含gpt-6.1-sol；不是模型名推测。
- 初测headless默认禁credentials导致MISSING_CREDENTIAL，未把无效覆盖部署。授权后仅项目patch credentials disabled=false + agent-default-model选择route/model，40秒no-tools真实请求返回ok=true。
- 用户随后发聊天明文密钥；本任务未使用/保存/写入命令或文件，提醒其已暴露应撤销轮换。不在Issue/Git记密钥或片段。
- 全量352 passed/107.30s；随后补manifest将*.patch.yml纳入code hash，防模型选择变化沿用旧审核，相关Harness/发布专项43 passed/83.25s。
- 只证明模型API推理有效，不代表web_search认证随之可用；headless搜索提供方独立，未设置或绕过其授权。

部署前active分析为空，既有restart成功，5020 PID65861健康检查通过。仅项目模型切换，无全局默认/密钥变更。未主动生成真实赛事推荐/发送通知或投注；提交推送结果以Issue与最终答复核验。
