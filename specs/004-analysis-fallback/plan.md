# Implementation Plan: Claude / Codex 后台分析

1. 新增 SQLite 任务状态与单任务并发门禁；后台 Python worker 独立于 gunicorn 请求。
2. `engine/providers.py` 封装本机 CLI：RTK 原始代理、结构化输出、研究工具约束、超时清理和固定错误分类。
3. `engine/tasks.py` 冻结输入与规则，按 Claude → Codex 顺序执行；保存草稿，不接入自动发布。
4. 接入 POST/GET 任务 API、管理员草稿详情页及前端轮询；保留现有认证、快照和正式报告路径。
5. 使用 Bleach 白名单清理新生成草稿的 HTML；外部 CLI、启动器和数据源均可模拟。
6. 逐个行为完成测试，再做 CLI 最小连通性检查、浏览器检查和正式部署。

## 复杂度与边界

- 独立 worker 是为了不受 gunicorn 的 60 秒请求超时影响；SQLite 原子门禁覆盖多 worker。
- 不增加调度、推送、自动下单、模型切换面板或自动发布。
- 草稿只新增到 `runs/<业务日>/<run_id>/`，任务/临时 CLI 文件属于 `var/`。
