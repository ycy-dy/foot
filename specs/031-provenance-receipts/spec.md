# 031 本地来源、引用与人工复核工件

关联Issue #14，作为024基础设施，不直接启用推荐门禁。

受信程序capture保存公开URL/调用方提供正文/时区时间/来源类型，正文2MiB限额，内容SHA256寻址；quote检查Unicode精确区间、正文hash、来源URL与match/option/dimension绑定；manual review由已鉴权调用者传actor/time，另写不可覆盖receipt。verify_support必须读取两个真实receipt并重验所有hash/时点/身份，AI自报verification_status无效。

工件O_EXCL/O_NOFOLLOW/0400，防目录穿越/符号链接；public URL只做语法限制，模块不访问网络，不证明正文来自URL。字面匹配不证明语义蕴含，人工行为认证/目录保护由集成调用者负责。攻击者若任意写整个目录可重造哈希，不宣称防本机全权限攻击。

验收：篡改、错身份/选项/维度、未来、赔率、无receipt、AI自报manual_verified、quote错位、路径/符号链接和大小边界反例。未接生产准入不得称legacy问题已解决。
