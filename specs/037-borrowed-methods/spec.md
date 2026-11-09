# 037 借用开源方法充实概率与评估基础设施

用户 2026-11-09 要求借鉴 GitHub 同类项目的功能与特色充实本项目。本规格只收口
**可验证的数学/评估基础设施**，不修改 014/036 业务政策，不改变推荐、发布与复盘行为。

借鉴清单见 [docs/open-source-borrowing.md](../../docs/open-source-borrowing.md)。

## 范围

1. 新增 `src/foot_web/engine/probability.py`，纯函数、无网络、无数据库、不新增第三方依赖：
   - Poisson 概率质量函数与比分矩阵；
   - Dixon-Coles 低比分相关修正（0:0、1:0、0:1、1:1）；
   - 胜平负、总进球（含整/半球线结算与走水）、让球（含走水）概率；
   - Elo 期望得分与更新（含净胜球乘数）；
   - 评估指标：logloss、Brier、ECE、校准斜率；
   - walk-forward 时间切分（train / calibrate / test + embargo）。
2. 配套单测 `tests/test_probability.py`，覆盖归一化、对称性、边界与指标性质。
3. 本文档记录来源与许可；不复制无许可仓库代码。

## 硬边界

- **不接入推荐链路**：本规格实现的任何函数都不得改变现有候选、评分、审核、发布、台账与复盘输出。
- **概率仍为 null**：模型未训练、未校准、未通过 027 预注册外样本验收前，页面与报告中的 `model_probability`、`EV` 保持 null；不得用本模块函数结果冒充模型胜率。
- **不改政策**：014 与 036 的 70 分门槛、条件票规则、提供方、人工发布、不投注边界均不变。
- **不新增依赖**：不引入 numpy/scipy/sklearn；纯 Python 实现，便于离线测试与回退。
- **不碰在途改动**：不修改 036 未提交的条件票代码与测试。

## 验收

- `pytest tests/test_probability.py` 全绿；完整回归不因本规格新增失败。
- 比分矩阵在 `rho=0` 时退化为独立 Poisson 乘积，且归一化总和为 1（1e-9）。
- 相同 λ 的主客队，胜/负概率相等；走水线概率可计算且三路（胜/走/负）和为 1。
- 完美预测的 logloss/Brier 接近 0；ECE 在 [0,1]；校准斜率可对合成数据返回有限值。
- walk-forward 各窗口 train/calibrate/test 不重叠，且按时间单调前进。
- 全仓 `compileall` 通过，`git diff --check` 无空白错误。
- 文档明确"未接入、未验证、概率仍 null"。

## 非目标

数据源适配器、T-24h/6h/90m 多时点快照、champion/challenger 晋级、LLM 评测基准、
事件数据接入均不在本规格实现，只作为 037 后续任务或独立规格。
