# 全页面按钮验收结果

2026-11-07，Issue #8，详细[控制件矩阵](control-matrix.md)。

## 已执行与修复

- 活动页面导航/表单action/script资源与admin/viewer角色矩阵27 passed；覆盖13个列表/静态页面，动态业务详情由对应专项fixture覆盖。
- 管理专项21 passed：计划/通知/持续监控未授权启用disabled并解释，后端拒绝403；保存停用303反馈；通知测试不enqueue；manual review/recheck/withdraw/cancel在mock下验证，错误安全转义。
- 分析控制+日志/任务动作/重新分析18 passed：null/畸形任务日志normalize、游标、filter/search/follow/download/cancel/resume/新任务、CSRF/发布确认与重复保护。未触发真实CLI/发布。
- 组合页面管理分析专项68 passed/1.79s；真实app.js Node VM验证主题切换、表单重复锁、submitter字段保持及后退恢复；4个JS文件node --check通过。
- 原首轮全量295 passed/2 failed，为旧测试预期全局409而当前管理路由正确先CSRF400并对有CSRF启用403；更新测试不弱化门禁。

## UI与生产边界

通过CUA打开生产5020登录页，显示钉钉登录和公共主题按钮。随后用户在Chrome切换到无关钉钉后台页面，工具拒绝沿旧索引点击；重新读取状态后停止控制，未提交授权/密码/组织选择。不能宣称所有按钮已在生产浏览器逐个点击。没有可用已认证浏览器表面，未伪造生产Cookie或开启替代服务。

其他页面均为隔离Flask客户端及真实JS VM/源码契约验收，不等于真实外部CLI、钉钉投递、企业OAuth权限或网络条件全部通过。计划/通知等政策禁用项目不是已实现自动运行。完整报告无文件404为预期状态。

最终全量297 passed/103.53s、退出0。随后小改全局gate确保无政策时仍可保存停用管理设置，该范围再次专项27 passed/0.60s；未再全量。Node通用脚本最终版本复验通过。现有restart成功，5020 PID17695；healthz ok=true，实际app.js?v5/analysis.js?v7/reviews.js?v4/rechecks.js?v2全部200。已部署，不宣称生产外部副作用都实际执行。
