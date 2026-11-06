# Plan: 定时分析与复盘

## Constitution Check
符合：不更换规则与提供方，不绕过推荐发布门禁，不投注，原票/history冻结。复盘是确定性结算，不新增Claude功能或SDK迁移。

## Architecture
- SQLite新增 schedules/schedule_fires/review_runs/review_current；沿用Store连接，新增存储类，建表幂等。
- scheduler服务由wsgi启动daemon线程，每20秒tick；跨进程flock短临界区 + 应执行时刻唯一键，先记触发再launch，崩溃可见interrupted，不自动重试造成重复调用。服务离线仅补15分钟，其他记录skipped。启用/编辑重新计算next_due。
- 赛前调用现有AnalysisTasks；忙时跳过并显式记录。复盘独立子进程，有独立全局活动任务门禁、状态持久化与死亡恢复。
- review服务纯函数结算，独立官方results抓取器（注入HTTP，超时分页上限），范围业务日到+2；严格终场与球队/编号校验，未知/冲突待核。Decimal原票盘口赔率、笛卡尔分支。
- 输入使用ledger/data/*records*.jsonl已知标准化冻结原票，去重、来源hash；不直接import历史脚本。输出runs/<date>/review-<id>/{tickets.json,results.json,settlement.json,review.md,manifest.json}，不产生report.md。
- review_current保存最新成功版本（日期级事务替换），Ledger可选读取该覆盖层，保留原数据cache，只替换对应稳定ticket_id；旧复盘不可变、失败不更新。
- 新页面 /automation 和 /reviews；手动POST form PRG，admin+CSRF；查看者只读；复盘详情安全渲染，不假装AI归因。

## Complexity Tracking
- 使用内置线程+flock，不新增调度依赖或额外launchd服务；每个gunicorn worker可tick，持久化unique防重复。线程异常记录日志后继续；健康页不做网络调用。
- 无通用异构历史票解析；只接受已知标准化输入，缺失明确失败。

## Validation
pytest隔离DB、模拟时钟/HTTP/launcher：并发到期、重启、过期跳过、忙冲突、权限/CSRF；纯结算边界、赛果身份、null、重算更正和原票冻结。浏览器隔离Chrome真实表单交互；全量测试后restart+healthz。
