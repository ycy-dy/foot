# 024 验证

2026-11-07，Issue #14。全维冲突专项7 passed；claim-aware反例覆盖缺hash/quote/locator、赔率claim、非人工核验支持关系，且legacy payload保持可读迁移兼容；P0相关发布/推荐专项42 passed，全量367 passed/105.29s。

Claim级新payload缺content_hash/quote/locator/retrieved_at/source_type或仅AI自报manual_verified时阻断新发布；旧legacy运行工件不追溯补证、不宣称新认证。后续完成数据迁移后可将policy切到claim强制模式。真实正文抓取/来源真实性人工复核仍未完成，不将字段存在称事实认证。
