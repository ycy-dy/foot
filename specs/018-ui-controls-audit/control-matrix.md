# 活动页面控制件验收矩阵

2026-11-07，Issue #8。以下是隔离fixture/假身份/模拟CLI/投递下的已执行测试，不是声称生产登录后逐个真实发送/发布。所有真实外部副作用均未触发。

| 页面／控制 | 验证与修复 | 方法／状态 |
| --- | --- | --- |
| 登录／退出 | OAuth入口/回调/白名单，logout CSRF与匿名失效 | auth测试；生产Chrome看到登录页，未操作OAuth授权 |
| 全站主题 | 切换dark/light、按钮标签；localStorage | 真实app.js Node VM；生产点击被用户切换标签中断，未冒报浏览器通过 |
| 移动导航／键盘 | 展开/收起、Escape、aria状态 | 脚本/DOM装配检查；无生产移动设备视觉验收 |
| 首页日期／重新分析 | date-query，script单装配，忙碌/提交失败，重复只建一任务 | recompute专项+真实JS模拟；无真实CLI |
| 首页逐场／梦想／台账链接 | 注册路由、资源200，空态不伪造，冻结数据只读 | page matrix、match/dream/daily测试 |
| 逐场详情／证据 | 足球/篮球队序、身份匹配、管理员完整页、viewer摘要、来源/details | match+research tests；GET不启动AI |
| 分析列表／任务 | 任务链接、cancel/resume、新建复用、invalid/null状态和错误反馈 | analysis/task/log tests；新增normalize容错 |
| 分析日志 | 筛选、search、follow/latest、download、增量游标、终态 | 日志/Node VM/DOM tests；无生产日志下载 |
| 审核／发布 | 真实脚本mock数据，CSRF、人工checkbox、confirm、重复锁、版本/变价/证据门槛 | publication+analysis controls，未真实发布 |
| 每日台账 | date查询，冻结票哈希、empty/withdrawn、原票复盘不双计 | daily tests；只读 |
| 历史日期／复盘 | 查询日期/切换、原票表、任务启动和复盘刷新 | history/review/task-action tests，CLI模拟 |
| 台账筛选／重置 | GET表单/action、日期/类别/状态/词、替代版本、reset | ledger tests+page targets |
| 统计／效果 | 月份/栏目/模式筛选、空态/原概率限制 | stats/evaluation tests |
| 完整报告 | 有文件则渲染/无则404，导航不伪造不存在报告 | reports/pages测试；可预期无报告404，不是按钮故障 |
| 复盘列表/详情 | viewer只读，admin手动POST/CSRF，policy不可用禁用提示，状态404/登录过期不循环 | management+reviews tests；reviews.js升级 |
| 定时计划 | 启用禁用并说明无授权；保存停用303及反馈；伪造启用403 | management controls；不会创建可运行计划 |
| 临场监控 | 持续监控启用禁用，保存停用可用；手动复核独立政策门禁 | management controls+mock |
| 发布详情／撤销 | admin当前版本可操作，CSRF/原因必填/错误HTML转义，版本保留 | mock recheck/withdraw测试，不撤销生产票 |
| 临场任务／取消 | running取消、终态隐藏控件，404/redirect停止重试，ID编码 | management+rechecks.js检查 |
| 钉钉通知 | 启用及测试发送禁用+原因，保存停用303反馈，后端无enqueue | management tests，绝不真实外发 |
| 执行版本 | 政策检查/哈希/details只读 | page matrix+versions tests |
| 操作日志 | admin可读/viewer403，所有链接可解析 | auth/page matrix |

旧index.html和policy_removed.html无活动路由，不视为当前页面；已删除体系编辑页面保持不存在。保留的源码旧模板不等于UI功能开放。

验收不是静态200全包：页面/角色矩阵验证链接和表单注册、资源和角色；业务测试验证写动作状态和门禁；Node VM验证真实JS关键行为；真实浏览器目前只确认生产登录页，其他浏览器动作受用户切换标签/无测试浏览器连接限制，未绕登录。真正的OAuth企业审批/外部CLI响应/官方网络/钉钉投递仍取决于真实条件。
