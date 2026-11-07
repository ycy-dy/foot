# 实施计划

执行层统计依据canonical工具开始事件，不能使用每次UI状态输出计数；Codex parser维护item身份/动作family/完成状态，完成仅展示，不重复携带预算标记。provider原有search/fetch计数继续以统一WebSearch/WebFetch事件累加，错误fail closed并清理。

Fetcher.latest_snapshot对文件一次read_bytes再JSON/hash，保留原文件；按文件时间排序回退，校验大小/envelope/日期，返回退回次数和stale。此为恢复不是数据认证，不解除发布时钟/可售门禁。
