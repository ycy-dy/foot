# 028 政策/文档一致性

- 每个当前入口只能有一个policy/manifest/runtime provider；自动检查README/AGENTS/governance/blueprint中的provider、启停和规则入口与policy一致。
- 旧013/021 Harness-only/Claude优先文案标历史或移除，不能给Agent漂移指令。
- 页面、CLI、Issue、提交台账中缺凭据/未训练/未真实验收边界统一措辞；测试检查文档关键状态。
- 版本manifest锁policy hash、scoring/patch/code hash、runtime provider/CLI版本/模型/endpoint capability fingerprint；模型身份未知null。
