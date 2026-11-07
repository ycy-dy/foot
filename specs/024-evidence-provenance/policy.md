# P0 证据溯源实施契约

审计发现当前证据层把AI自报tier/group/time当可信元数据，且评分只检查11个加权维度；这不能称国际级可信。024先做fail-closed，不改历史。

## Claim级字段

每个可用非赔率claim必须带：claim_id、match_key、dimension_id、option_id（适用时）、claim、source_id、source_type（non_odds/odds/unknown）、source_tier、published_at、effective_at、retrieved_at、content_sha256、quote、locator、evidence_group_id、support_status（supports/contradicts/context/unknown）、verification_status（unverified/agent_reported/manual_verified）。

缺content_hash/quote/locator/retrieved_at/source_type，或仅有AI自报manual_verified，不能进入可发布70分；按unknown/blocked处理。source_type=odds不能满足非赔率理由。claim必须实际支持所选option，context/contradicts不能加分；同一content_sha/group只计一次。公开来源原文抓取必须有大小、协议、重定向和敏感URL限制；失败显示unknown，不补摘要。

## 全维冲突

23个维度任何`conflict`默认阻断该场/选项。赔率维度冲突也不由其他分补偿；若政策未来允许市场诊断冲突不阻断，必须新版本明确声明。关键维度仍需48小时verified和非重复来源；70及其余评分规则不改变。assessment source_ids必须指向支持所选option的confirmed non-odds claims。

## 发布与回滚

发布重算claim hashes/source support/effective time/评分；快照变化拒绝，不静默换腿。记录score_version/provenance_coverage/support_precision/manual_review；不能将证据分叫置信胜率。旧runs/ledger/reports只读，不追溯补字段或重发。
