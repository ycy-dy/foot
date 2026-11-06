# 计划

复用已有research_matches/ResearchStore和match_key，新增只读projection，GET不启动AI、不写原票。首页每场详情链接，比赛页共用摘要partial；管理员完整证据页增加逐选项评分。记录匹配只用精确身份，同业务日/队序/开球均入hash；当前版本标记与按查看时点重算评分避免旧来源冒充当前建议。

测试首页链接、未分析、身份变化不匹配、低分、viewer只读与admin证据权限。全量回归后重启既有5020服务，更新Issue、台账，commit/push，不启用自动通知。
