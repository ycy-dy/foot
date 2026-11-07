# 025 时点数据与不可变快照

目标：保证赛程/赔率/身份在决策时点可复算，不把一次抓取成功称为数据质量合格。

## P0/P1契约

- 比赛对象必须有稳定官方match/team ID；名称变化不能隐式产生新身份。缺ID时保留显示但禁止推荐。
- 快照文件采用纳秒/UUID唯一名，保存payload sha256、captured_at、source_update、HTTP状态/schema版本、解析器版本；写后读回哈希；损坏快照隔离，不回退为fresh。
- source_update晚于captured_at、时钟异常、schema漂移、必需市场缺失或非finite/非正赔率进入quality gap；发布拒绝stale/身份/市场互斥不完整。
- 训练/评估只使用as_of前特征，结果延迟和时区固定；缓存复用记录原as_of与规则/代码/provider hash。

## 验收

重复同秒抓取100次文件唯一、哈希一致；截断/畸形/漂移/源时钟反例阻断；名称改动同ID可追踪、ID冲突拒绝；旧快照只读。模型未验收仍null。
