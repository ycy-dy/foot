# 开源借鉴清单（2026-11-09）

目的：把 GitHub 同类项目中**可复用、可验证、不越界**的方法吸收进本项目，补上当前
"概率层为空、赛前时点单一、缺少公开评测基准"的短板。本文只记录借鉴关系与边界，
不构成业务政策；现行政策仍以 [规格014](../specs/014-evidence-gated-recommendations/policy.md)
与 [规格036](../specs/036-required-conditional-pairs/spec.md) 为准。

落地入口：[规格037](../specs/037-borrowed-methods/spec.md)。

## 1. 借鉴矩阵

| # | 借鉴什么 | 来源项目（许可） | 落到本项目哪里 | 当前状态 | 优先级 |
| --- | --- | --- | --- | --- | --- |
| 1 | Dixon-Coles 低比分修正、Poisson 比分矩阵、Elo 期望/更新 | [penaltyblog](https://github.com/martineastwood/penaltyblog)（MIT）、[football-prediction-skill](https://github.com/JetQiao/football-prediction-skill)（MIT）、[wc26-predict](https://github.com/AndyDu0921/wc26-predict)（MIT） | 新增 `src/foot_web/engine/probability.py` | 已实现原语，**未接入**推荐/发布，概率仍 null | P0 |
| 2 | 概率评估指标：logloss、Brier、ECE、校准斜率 | 同上 | 同一模块，供 [027](../specs/027-model-readiness/spec.md) 模型就绪门槛使用 | 已实现，待接评测 | P0 |
| 3 | walk-forward 时间切分（train/calibrate/test + embargo） | [football-prediction-skill](https://github.com/JetQiao/football-prediction-skill)、[wc26-predict](https://github.com/AndyDu0921/wc26-predict) | 同一模块 `walk_forward_splits`，后续接入 [026](../specs/026-frozen-evaluation/spec.md) | 已实现切分原语 | P1 |
| 4 | 赛前时点截断 T-24h / T-6h / T-90m，收盘赔率不得冒充早期基线 | [football-prediction-skill](https://github.com/JetQiao/football-prediction-skill) | [025](../specs/025-pit-snapshots/spec.md) 由"单时点快照"升级为"多时点快照" | 未实施 | P1 |
| 5 | champion/challenger 晋级门槛，任何入口不能静默绕过 | [football-prediction-skill](https://github.com/JetQiao/football-prediction-skill) | 027 模型注册增加晋级协议 | 未实施 | P1 |
| 6 | Agent 只读数据契约：不下注、不索要密钥、外部文本视为不可信数据、必须携带来源/时效 | [sports-skills](https://github.com/machina-sports/sports-skills)（MIT） | `docs/` 增补"外部数据契约"，并作为研究提示词的一部分 | 未实施 | P0 |
| 7 | 统一多源赛程/结果抓取适配层 | [soccerdata](https://github.com/probberechts/soccerdata)（无明确许可，仅借鉴设计） | `src/foot_web/data/` 增加适配器，保留官方快照优先 | 未实施 | P2 |
| 8 | 事件级数据与 VAEP/xT 估值，支撑 xG/回合效率维度 | [hudl/open-data](https://github.com/hudl/open-data)、[socceraction](https://github.com/ML-KULeuven/socceraction)（MIT） | 仅在证据维度研究侧使用，不进入推荐硬门槛 | 未实施 | P2 |
| 9 | 用真实赛事评测 LLM/deep-research agent 的公开基准 | [WorldCupArena](https://github.com/wzk1015/WorldCupArena)（MIT） | 新建研究侧评测集，验证 AI 取舍质量 | 未实施 | P1 |
| 10 | 赔率抓取（oddsportal 等） | [OddsHarvester](https://github.com/jordantete/OddsHarvester)（MIT） | **不引入**：继续以官方快照为准，避免抓取合规与时效风险 | 明确不借鉴 | — |

## 2. 明确不借鉴的东西

- **博彩执行链路**：任何下单、代客操作、资金流接口。本项目不接入投注、支付或下单，边界不因借鉴而放宽。
- **无许可/无源码的高准确率宣称**：网上流传的 "WINNER12 W-5 多智能体框架" 声称开源且准确率 86.3%，实际仓库 `Winner12-AI/w5-football-prediction` 返回 404，只剩 ★1 的复现仓库。凡"高准确率 + 开源地址"先验真伪。
- **占位式模型输出**：不把 Poisson/Elo 的原始概率直接写进推荐，也不把 `p_mkt` 冒充模型胜率。模型概率只有在 027 的预注册外样本门槛通过后才可输出，否则保持 null。
- **Selenium 抓取商业博彩站点**（如 `bet365-scraper`）：违反站点条款、稳定性差，且与本项目"官方来源优先"的原则冲突。

## 3. 吸收方式（方法论）

1. **只借方法，不借结论**：开源项目的 README 准确率、收益率一律不引用为本项目证据。
2. **先纯函数后接线**：数学原语先做成无网络、无数据库、可单测的纯函数，再接评测，最后才谈推荐链路。
3. **许可分级**：MIT/Apache 可参考实现并注明来源；无许可证的仓库只借鉴设计思路，不复制代码。
4. **不新增重依赖**：当前环境无 numpy/scipy/sklearn，概率原语用纯 Python 实现，避免为一个未验证模型引入科学计算栈。
5. **可回退**：任何借鉴能力默认关闭，由规格与开关控制，不改变现有发布/复盘行为。

## 4. 与现有规格的关系

| 规格 | 关系 |
| --- | --- |
| 014 / 036 | 业务政策不变；本清单不改变 70 分门槛与条件票规则 |
| 025 | 借鉴项 4 是其后续增强 |
| 026 | 借鉴项 2、3 为其提供评测原语 |
| 027 | 借鉴项 1、2、3、5 的服务对象；门槛不变 |
| 037 | 本清单的实施规格 |

## 5. Issue 登记（待同步）

本机 `gh` 不可用、无可用令牌，按 [Issue 协作规范](issue-workflow.md) 先本地登记，
恢复后补建：标题「P1 借用开源方法充实概率与评估基础设施」，关联 Issue #14（模型验证
与风险路线），正文要点即本清单第 1 节 1–5 项与规格037。提交说明暂用 `Refs #14`，
不得冒报已创建。
