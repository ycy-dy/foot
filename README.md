# foot

足球＋篮球赛事研究 AI Agent 系统。

代码仓库：https://github.com/ycy-dy/foot

默认分支：`main`。当前以已提交源码的干净根提交建立GitHub历史；旧历史仅保留本地备份，不推送。

面向足球与篮球赛事研究、证据整理、工程开发、审核与冻结复盘的项目，配套 Web 控制台。系统只做研究与展示，不接入投注、支付或下单，不保证命中或收益。

## 当前状态（2026-11-06）

- 当前执行[规格014](specs/014-evidence-gated-recommendations/spec.md)：沿用用户确认的分段与玩法要求，新增每选项证据可信度>=70%硬门槛，低于或无法可靠评分不推荐。
- 首页显示当日赛程、已审核发布的推荐和[每日台账](docs/daily-recommendations.md)入口。真实当前政策提供方研究、候选算术、AI决策、发布审核与次日复盘相互分离；模型未部署不编概率/EV。
- [规格023](specs/023-search-codex-fallback/spec.md)：用户授权Harness搜索不可用则用Codex CLI替代，当前唯一提供方codex。Harness/pixmoving仍可显式政策切换，不在单任务混合回退，不调用Claude。所有工件提供方与manifest匹配，旧结果不冒充新成功。
- 原V6文件与编辑器仍删除，不恢复；现行契约为014的policy.md/policy.yaml/scoring.md。定时计划和通知仍默认停用，另行授权。
- `specs/001`–`specs/012` 仅作为旧实现记录保留，不是现行业务政策；规格006目录已删除，不得建立指向它的活动链接。
- `history/` 已按用户确认删除，不恢复。已有 `runs/`、`ledger/`、`var/` 等运行工件不因本次文档整理删除或改写。

## 需求、问题与 Agent 交接

每次新增需求或处理新问题，都先创建或更新 [GitHub Issues](https://github.com/ycy-dy/foot/issues)，记录进展、验证、提交和遗留项。其他Agent先查看开放Issues及相关讨论；完成验收后才关闭。详见 [Issue协作规范](docs/issue-workflow.md)。

## 阅读入口

- [项目认知与上手指南](docs/project-knowledge.md)
- [项目治理与阅读地图](docs/project-governance.md)
- [AI Agent 系统蓝图](docs/sports-agent-system.md)
- [目录约定](docs/directory-layout.md)
- [逐场分析规格](specs/015-per-match-analysis/spec.md)：首页每场进入详情，查看已保存AI研究、证据分、玩法理由和风险；无结果标待分析。
- [梦想比分4串1](specs/016-dream-score-ticket/spec.md)：首页独立栏目展示已审核发布四场准确比分，逐腿≥70证据分，不足不凑单，独立台账与复盘。
- [代码提交修改台账](docs/commit-ledger.md)：每次提交记录修改、验证和推送状态；提交后必须推送既有远程上游。
- [.specify/memory/constitution.md](.specify/memory/constitution.md)

## 工程开发

```sh
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e '.[dev]'
cp .env.example .env
.venv/bin/python -m pytest
```

开发遵循 `spec → plan → tasks → analyze → implement`。测试、部署与真实AI验收分别记录于对应verification；不以服务启动或离线fixture证明预测可靠。

## 安全与边界

系统不接入投注、支付或下单接口，不追损加码，不承诺收益。资料缺失时保留待核/null，不编造赛程、赔率、首发、概率或结果。任何新业务政策都必须先获得用户确认，形成规格013及机器可读契约，再实现、测试和审核。
