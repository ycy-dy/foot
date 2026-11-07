# 017 修复重新分析点击无响应

用户反馈首页按钮无反应，Issue #7。

## 根因

新recommendation_dashboard未加载analysis.js；按钮缺span，控制器render解引用null。旧HTML仅静态测试未验证script装配。

## 修复与验收

管理员首页加载一次版本化analysis.js，标准button type与文字span；控制器回退按钮本体避免null。提交后禁重复/显示忙碌、后台任务轮询日志、CSRF及管理员权限不变；错误固定显示在analysis-status并toast，超时说明状态未确认勿重复提交。viewer不加载提交控制器、不显示按钮。

测试页面DOM/资源、API两次请求只launch一次及reused反馈；真实CLI不因测试启动。全量后重启现有服务并静态资源验证；浏览器完整点击是否验收单独记录。
