# Analyze

现行014/023/034不变，未修改数据/评分/发布。latest_analysis原SQL的全局active OR业务日把展示和准入混在一起；拆为同日展示和独立active查询，start仍事务性begin_analysis，不能靠前端文案绕全局唯一索引。任务曾失败不冒称成功，action只表达下一步操作。取消前无研究尝试不称重新分析。
