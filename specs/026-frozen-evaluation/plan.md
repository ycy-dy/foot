# 实施计划

审核阶段用刷新官方source按固定engine算法枚举市场基准，只作研究对照，不是推荐，不需AI/证据70但保留身份/可售/未开赛/结构/成本硬规则。冻结标准settlement ticket、时段空原因、方法/schema/provider/manifest/source/content hashes到baseline.json；发布ID绑定content hash。

Evaluation完全移除当前build_bundle/选腿调用，只读验证冻结工件与发布/source时间/哈希/概率/身份。不修改原票/基准，不用缺工件历史回算。有或无AI各自availability，只有同slot结果/事前概率齐全才比较；置信区间后续研究，不假称当前完成。

测试真实PublicationService输出直进Evaluation，带官方result fixture、读前后文件相同，缺文件/篡改/未来/source/provider/schema错报gap，纯市场基准不从无证据AI bundle生成。
