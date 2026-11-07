# 计划

复用providers.generate取消/超时/进程组回收，新增harness分支/最终事件解析；command固定dsh headless与项目patch，清除当前DSH session/web/profile环境避免接管交互会话。schema作为stdin契约追加，最终validator仍确定性执行。

workflow/decisions/review/selection/versions/config同一提供方迁移，旧unit parse只作历史兼容不作为运行入口。PublicationsService复制harness.response.json，UI标签及日志filter适配harness。reuse要求same_version包括代码/提供方和harness来源。

CLI实际help/source已读，patch组合不打印用户配置；真实最小探测临时目录、只读无工具，不包含比赛/凭证。完整事件final才成功，思考不公开。无需新SDK/API账号；不改当前Harness GUI服务或原profile。package-data包含patch，部署现有foot5020而非另开服务器。
