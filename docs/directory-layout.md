# 项目目录约定（2026-11-06）

| 目录/文件 | 用途 | 当前规则 |
| --- | --- | --- |
| `AGENTS.md`、`CLAUDE.md` | 智能体规则入口 | 当前业务体系和页面已删除；遵循工程安全与不投注边界 |
| `docs/project-knowledge.md` | 项目认知与上手说明 | 不替代业务规则；当前不生成分析或推荐 |
| `analysis_recommendation_system_v6_0.md/.yaml` | 已删除的旧体系源文件 | 不得恢复、读取或引用；新业务政策待规格013 |
| `.specify/`、`.claude/skills/speckit-*` | Spec Kit（SDD） | 宪法在 `.specify/memory/constitution.md` |
| `specs/001-*/`至`specs/012-*/` | 旧功能规格记录 | 仅作旧实现记录，不是现行政策；规格006目录已删除，不建立链接 |
| `specs/013-*/` | 新业务政策规格（若创建） | 必须用户确认后才可授权实现 |
| `src/foot_web/` | Web 系统代码 | 不因本轮文档整理改写 |
| `tests/` | pytest 测试 | 不因本轮文档整理改写 |
| `tools/` | 工程核对、审核和迁移工具 | 不据旧规则生成当前推荐 |
| `deploy/` | 启动脚本、launchd 配置 | 本轮不部署 |
| `ledger/` | 历史命中率和结算台账 | 运行工件冻结，不删除或改写；投注金额与返还固定为 null |
| `runs/` | 分析、草稿、审核和发布运行工件 | 只读核对，不覆盖、不伪造成功 |
| `var/` | SQLite、快照、日志和运行时数据 | 不删除或改写 |
| `history/` | 已删除的历史产物目录 | 不恢复 |
| `docs/` | 架构、目录和迁移说明 | 统一导航见 `docs/project-governance.md` |
| `.env` | 密钥和配置 | 权限600，git 忽略；模板见 `.env.example` |

用户后续已授权规格014：现行policy.md/policy.yaml/scoring.md定义分段推荐、70%证据硬门槛和每日冻结台账。新草稿在runs/业务日/任务ID保存daily-ledger.draft.json，人工发布后publication目录冻结daily-ledger.json；台账页面/daily-ledger引用原发布，不另计票数。旧V6源文件/编辑器及history不恢复；自动计划与通知保持停用。上表删除状态描述为013阶段历史，现行以本段和014为准。
