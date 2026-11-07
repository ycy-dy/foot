# 028 政策/文档一致性与基础Web安全

在策略一致性之外，本轮补充低风险安全头和Secure Cookie opt-in；TLS终止不在Flask内默认强制，公网应由TLS反向代理承担。

- 每个当前入口只能有一个policy/manifest/runtime provider；自动检查README/AGENTS/governance/blueprint中的provider、启停和规则入口与policy一致。
- 旧013/021 Harness-only/Claude优先文案标历史或移除，不能给Agent漂移指令。
- 页面、CLI、Issue、提交台账中缺凭据/未训练/未真实验收边界统一措辞；测试检查文档关键状态。
- 版本manifest锁policy hash、scoring/patch/code hash、runtime provider/CLI版本/模型/endpoint capability fingerprint；模型身份未知null。
