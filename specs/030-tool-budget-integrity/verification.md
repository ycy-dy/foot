# 030 验证记录

本轮Codex原生网页事件按item.id分类并幂等计数：search/query为WebSearch，open/open_page/find为WebFetch，started/updated/completed重复不重复扣预算，完成先到也先扣一次。无ID/动作未知/类型冲突及非白名单工具fail closed且清理进程；整理禁工具不可绕过。工具参数/结果和reasoning不写公开日志。

快照恢复改为每文件最大20MB+1有界读取，坏JSON/envelope/时钟跳过但不修改，返回stale/skipped计数；全部坏则无数据。

专项58 passed/11.97s。首轮全量430通过1失败，为旧隐私测试期待公开原search query；新版只公开canonical工具名，更新断言保留脱敏与私有内容不出现要求。最终全量431 passed/174.87s，active为空后现有restart成功5020 PID60549健康；未真实CLI/网络探测，不把合成协议验证声称新版CLI线上事件全覆盖。
