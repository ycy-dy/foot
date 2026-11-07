# Harness迁移验证

2026-11-07，Issue #11。

## 已核实

本机dsh路径/正式headless --json stdin用法已用--help核实；headless官方实现final.text为完整最终答案，thinking单独事件，工具call/result独立。项目patch组合成功，不改用户全局配置/凭证。新manifest runtime_provider=harness，新决策仅接受harness工件/全部harness尝试，旧CLI成功与复用拒绝。日志storage allowlist支持harness，旧日志可只读显示。

研究patch禁shell、文件、技能、子代理、工作流、目标、插件管理，只保留web，整理另关闭web；read-only sandbox。每个调用独立headless Session，不传DSH_SESSION_ID/currentGUI。调用仍有取消/超时/进程组回收和原JSON校验；最终schema失败不得成功。思考事件不写公开日志。

## 真实有界探测

- 40秒no-tools最小JSON返回{'ok':true}，证明实际Harness执行与最终结果解析，不是模板。
- 40秒web工具探测实际出现web_search tool_call/result，最终url null。35秒带failure摘要探测明确原因：缺少可用搜索API密钥。headless默认搜索提供方使用DEEPSEEK_API_KEY，本任务没有索取/复制/显示任何凭证或修改用户profile；**不声称比赛联网调研已可用**。
- headless模型/额度由其自身配置决定，不保证等于当前GUI会话；当前model None不冒报具体模型。

## 自动化与部署

Harness命令/事件/最终返回/唯一路由/无CLI回退/工件哈希专项22 passed；Lead独立最终完整回归351 passed/102.53s、退出0。此前并行src修改引发一次manifest哈希不一致，停止修改后独立复验全绿。无active分析后现有restart成功，5020 PID14201健康。无生产任务启动、通知、自动发布或投注。搜索授权缺口与真实赛事链路仍保留待验收，不偷偷回退CLI。
