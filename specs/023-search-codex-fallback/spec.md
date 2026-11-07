# 023 搜索不可用时切换Codex CLI

用户明确新授权：能解决Harness搜索则解决，不能则使用Codex CLI替代。当前headless已授权模型pixmoving可推理，但无可用正式搜索凭据，不能自动创造权限/付费或将Chat Completions密钥冒用搜索接口。

## 执行政策

当前policy decision.runtime_provider=codex/providers[codex]，不调用Claude。Harness可显式policy选择保留，不逐次失败静默混合回退；所有研究/最终决策/复盘统一当前提供方。active_provider/rules_manifest唯一来源，配置显式选择必须与policy一致，旧工件与提供方不匹配拒绝。

Codex原生standalone_web_search，禁host/code/shell/MCP/hooks/plugins；只读sandbox、不安装host。若PATH命令缺失但官方npm entry已存在且可执行，可复用官方入口，不下载或擅自改用户全局链接。本机发现CLI已从0.155.1变0.167.0，实测参数再使用。

最终真实schema验证、来源/70门槛/人工发布/日台账保持。无效草稿不成功，思考不公开，配置错误仍可快速失败。不得宣称小搜索证明完整赛事研究；单独列版本及host错误是否存在。
