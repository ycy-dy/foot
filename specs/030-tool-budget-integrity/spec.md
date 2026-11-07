# 030 工具预算幂等与坏快照恢复

关联总审计Issue #14。补齐Codex工具事件流语义：同item.id的started/updated/completed只计一次，按action明确区分search和open/find fetch，乱序completed-first保守计数，缺ID/冲突/未知动作不得绕过预算。仅公开事件，不能暴露reasoning或开启额外工具。

快照恢复按新到旧只读扫描有界JSON，坏文件/错误envelope/非法时钟跳过并标skipped_invalid_snapshots/stale，不修改坏文件，不把旧快照当fresh。全部不可用返回None，原网络错误不伪造数据。

验收：重复/乱序/类型冲突/未知事件与search-fetch预算反例；坏最新回退、全部坏、文件保持不变及20MB限制。全量后无active再部署，Issue/台账commit/push，不真实比赛AI/消息/投注。
