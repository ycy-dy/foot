# 027 模型就绪与时间外验证

只建立模型注册/实验验收契约，不因规格存在替换p_mkt或启用模型推荐，关联Issue #14。

- 时点特征、标签延迟、来源快照、模型/代码/数据哈希和参数注册。
- rolling date/round train-calibrate-test，purged/embargo，所有市场同折；概率指标logloss/Brier/ECE/校准斜率与置信区间；按联赛/玩法/赔率段分组和cluster bootstrap。
- 与简单实力、当时可得市场基准比较；选择子集与全候选分离；多重筛选/共享比赛依赖披露。
- 不足样本、分布漂移、模型失败、概率不确定性明确；未满足预注册外样本标准，model_probability/EV继续null。
