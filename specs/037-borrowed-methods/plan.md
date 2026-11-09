# 037 Plan

1. 写借鉴清单（`docs/open-source-borrowing.md`）：来源、许可、落点、优先级、不借鉴项。
2. 实现 `engine/probability.py` 纯函数：Poisson/DC 比分矩阵、1X2、总进球、让球、Elo、评估指标、walk-forward。
3. 写 `tests/test_probability.py`：归一化、对称性、走水、指标性质、切分不重叠。
4. 只跑新增单测与完整回归，不启动服务、不改数据库、不改政策文件。
5. 文档标注"未接入、未验证、概率仍 null"；提交只包含新增文件与台账。
6. 后续项（不在本次）：多时点快照（025 增强）、champion/challenger（027 增强）、数据适配器、LLM 评测基准。
