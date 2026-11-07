# 026 验证记录

## 本轮真正冻结闭环（取代下文早期未完整实现说明）

新建evaluation_baseline.py在审核阶段按刷新source枚举纯市场研究对照（非推荐），冻结baseline.json并publication绑定schema/source/manifest/provider/content哈希。Evaluation不再调用build_bundle，只验证冻结标准票；缺工件不补算，篡改/未来/提供方/schema/hash不符明确gap。真实PublicationService→Evaluation集成无mock选腿，校验文件不变与缺基准不回填。去除source_update fixture字符串生产豁免，官方ID缺失保持None不冒充编号，match_key绑定完整身份。

专项38 passed；最终完整385 passed/172.95s，active为空后restart5020 PID53047健康。市场基准不等于推荐，不替代70门槛；cluster CI/模型OOS仍未完成。


2026-11-07，Issue #14 P0-C。

- 修复PublicationService.check/publish冻结审核audit包含source和source_sha256，供evaluation读取冻结输入；缺source明确记录gap，不用KeyError假装性能。
- Evaluation对缺source/旧工件保守跳过并记录缺口；不从当前算法补算baseline，不改历史纯结算。
- 现有发布/评估专项25 passed/78.40s；因旧隔离fixture无source首轮全量358通过3失败，兼容缺source后最终全量361 passed/100.02s，退出0。
- 这是契约和测试修复，不是已完成预测模型、时间外验证或盈利证明；baseline/AI概率缺失仍null/gap。