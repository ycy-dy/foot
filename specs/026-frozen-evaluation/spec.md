# 026 冻结评估与市场基准契约

P0发布→评估集成契约修复，关联Issue #14。

- PublicationService.freeze audit与official/source字段提供evaluation所需完整schema；禁止评估从缺字段猜测或用当前算法重算冻结baseline。
- baseline、AI候选、官方结果必须共享冻结match identity、as_of、规则/代码/模型/provider hash；缺一项明确gap，不将KeyError算性能。
- 评估只读、无网络/AI/发布副作用；p_mkt/模型概率/EV和证据分分列。无训练模型仍null。
- 预注册时间切分、选择子集/全候选、共享比赛依赖、待定/取消和cluster CI字段；不宣称国际领先或盈利。

## 验收

真实PublicationService输出直接喂Evaluation的集成fixture无patch；audit/source/schema哈希一致；baseline缺失或概率缺失可解释gap；选择偏差、分组和置信区间字段存在；历史纯结算不被新评估覆盖。
