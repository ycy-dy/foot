# foot

足球＋篮球赛事研究 AI Agent 系统。

代码仓库：https://github.com/ycy-dy/foot

默认分支：`main`。保留既有提交历史，不重新创建空仓库。

面向足球与篮球赛事研究、证据整理、工程开发、审核与冻结复盘的项目，配套 Web 控制台。系统只做研究与展示，不接入投注、支付或下单，不保证命中或收益。

## 当前状态（2026-11-06）

- 原分析／推荐体系及其页面已按用户确认删除；当前没有生效的足球或篮球业务政策。
- 新的分析、推荐、审核发布、定时任务和通知均停用，待新的用户确认规格 **013** 及机器可读契约建立后再恢复。
- `specs/001`–`specs/012` 仅作为旧实现记录保留，不是现行业务政策；规格006目录已删除，不得建立指向它的活动链接。
- `history/` 已按用户确认删除，不恢复。已有 `runs/`、`ledger/`、`var/` 等运行工件不因本次文档整理删除或改写。

## 阅读入口

- [项目认知与上手指南](docs/project-knowledge.md)
- [项目治理与阅读地图](docs/project-governance.md)
- [AI Agent 系统蓝图](docs/sports-agent-system.md)
- [目录约定](docs/directory-layout.md)
- [代码提交修改台账](docs/commit-ledger.md)：每次提交记录修改、验证和推送状态；提交后必须推送既有远程上游。
- [.specify/memory/constitution.md](.specify/memory/constitution.md)

## 工程开发

```sh
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e '.[dev]'
cp .env.example .env
.venv/bin/python -m pytest
```

开发遵循 `spec → plan → tasks → analyze → implement`。本轮只清理文档入口，不恢复已删除体系，不宣称运行时测试、发布或部署完成。

## 安全与边界

系统不接入投注、支付或下单接口，不追损加码，不承诺收益。资料缺失时保留待核/null，不编造赛程、赔率、首发、概率或结果。任何新业务政策都必须先获得用户确认，形成规格013及机器可读契约，再实现、测试和审核。
