# 029 服务就绪探测

关联总审计Issue #14。保留公开/healthz作为进程存活，新增公开/readiness检查当前SQLite核心表和policy契约，无模型/抓取/发送副作用。

数据库使用mode=ro和250ms连接超时，缺文件不创建空库，缺核心表或政策不可用返回503；成功200。公开JSON仅ready和checks.db/checks.policy，不暴露路径、异常详情或凭据。此探测不是完整模型、搜索、外部OAuth或预测能力检查。

验收：匿名成功、数据库不存在不创建、空库失败、政策错误脱敏、health与readiness区别，测试后空闲部署并真实检查JSON/状态而不是重定向登录页的200。
