# 提示词：竞彩足球/篮球分析推荐 Web 系统（v0.2，2026-11-04 用户已确认）

> 用途：把下面“提示词正文”整体交给开发智能体（Claude Code），在 `/Users/ycy/ycy/foot` 下实现系统。方括号【】里是可配置的默认值。

---

## 提示词正文

你要在 `/Users/ycy/ycy/foot` 项目中实现一个**前后端一体的竞彩足球/篮球分析推荐 Web 系统**。用户通过浏览器访问 `http://<服务器IP>:<端口>`，用钉钉账号登录后，查看当天的足球、篮球赛程，以及由 Claude Agent 按本项目体系生成的分析和推荐。

### 1. 必须先读的项目资料
- `AGENTS.md`：项目规则总入口（业务日窗口、分段、六类玩法、八结构、单项≥1.33、组合赔率>2.5硬门槛、每组理由、最终推荐汇总、梦想单、篮球客前主后等）。
- `analysis_recommendation_system_v6_0.md` / `.yaml`：当前体系 V6，修订 `2026-11-04-hitrate-01`，重点是第20节（市场基准概率 p_mkt、按命中概率排序、20.8 逐项理由、20.9 早中场合并、20.10 最终汇总、20.11 2.5 硬门槛和发布前审核）。
- `analysis_2026-11-04_hitrate/`：一次完整分析的参考实现，包括 `analyze.py`（抓取后计算 p_mkt、候选、结构组合）、`build_report.py`、`apply_reasons.py`、`apply_merge.py`、`report.md`、`recommendations.json`。
- `system_upgrade_2026-11-04/audit_recommendations.py`：发布前审核脚本，不通过不得展示为“已发布”。
- `recommendation_hit_rate_ledger.md`、`ledger_data/`：命中率台账和赛果数据。
- 钉钉登录参考：`/Users/ycy/pix/version_ctrl_console/auth_service.py`、`app.py`、`static/js/login.js`、`.env.example`。

不要改动 V6 体系文档、历史报告和历史原票；系统只调用和展示它们。

### 2. 技术栈（默认，与参考项目一致）
- 部署：**本机（macOS，当前用户 ycy）**。后端 Python 3 + Flask，用 gunicorn 监听 `0.0.0.0:5020`，访问地址 `http://172.16.37.247:5020`（局域网 IP 以启动时实际值为准，变化后要同步改钉钉回调地址）。用 launchd 做开机自启和崩溃重启。服务必须以 ycy 用户运行，才能使用本机已登录的 claude。定时任务要求机器不休眠，README 要说明 `caffeinate` 或 `pmset` 的设置。
- 前端：Flask 模板加原生 JS/CSS，不引入重型前端框架。要求移动端可读（用户常用手机看）。
- 存储：SQLite（`web/data/app.db`），保存用户、会话、分析任务、推荐快照、审计日志。
- 配置：`.env`，提供 `.env.example`。密钥不入库、不提交 git。

### 3. 钉钉登录（参考 version_ctrl_console 的实现方式）
- 流程：`/auth/dingtalk/begin` 生成 state 并存入 session，跳转 `https://login.dingtalk.com/oauth2/auth`（参数 client_id、redirect_uri、response_type=code、scope=openid、prompt=consent、corpId、state）。
- 回调 `/auth/dingtalk/callback`：校验 state 和有效期，用 code 换 `userAccessToken`，调 `/v1.0/contact/users/me` 取 unionId 和姓名，再用企业 token 调 `user/getbyunionid`、`topapi/v2/user/get` 确认是本企业成员。
- **复用 version_ctrl_console 的钉钉应用**：沿用同一套 `DINGTALK_CLIENT_ID`、`DINGTALK_CLIENT_SECRET`、`DINGTALK_CORP_ID`，值从该项目的 `.env` 复制到本项目 `.env`，不得写进代码或 git。需要在钉钉开放平台为该应用**新增登记回调地址** `http://172.16.37.247:5020/auth/dingtalk/callback`（`DINGTALK_REDIRECT_URI`），原项目的回调不动。
- 权限：**只有白名单里的人能登录**。白名单为 `FOOT_ALLOWED_USER_IDS`（钉钉 userId，逗号分隔），不在名单内的企业成员也拒绝，并记录日志。名单内再分 admin（`FOOT_ADMIN_USER_IDS`，可触发分析、复盘、改定时）和 viewer（只读）。
- 安全：session cookie 设 HttpOnly、SameSite=Lax；回调校验 state；登录、登出、触发分析都写审计日志。未登录访问任何页面或 API 都跳转登录页。

### 4. 数据获取（后端定时加按需）
- 竞彩官方：
  - 足球 `https://webapi.sporttery.cn/gateway/uniform/football/getMatchCalculatorV1.qry?channel=c`
  - 篮球 `.../basketball/getMatchCalculatorV1.qry?channel=c`
  - 赛果 `getUniformMatchResultV1/V2.qry`
- 交叉源：鸿裕 `https://hy.xcryzs22.cn/livescore/v2/{sport}/{yyMM}/{dd}/{date}.json`（与现有 fetch_sources.py 一致）。
- 每次抓取保存原始 JSON 快照（带时间戳和 sha256），不覆盖旧快照。
- 定时：业务日内每【30】分钟刷新赔率和在售状态；开赛前【60】分钟起每【10】分钟刷新一次。

### 5. 页面
1. **登录页**：钉钉扫码或跳转登录。
2. **今日总览（首页）**：
   - 顶部是“最终推荐汇总”卡片，按足球早中场①、足球晚场②、篮球早场、篮球晚场排列，每组显示两腿、赔率或分支、命中估算 p、每组理由、风险、撤销条件；梦想单放最后。显示数据快照时间和审核状态（通过/不通过）。
   - 足球赛程表：按早/中/晚场分组，列出编号、时间、赛事、主队VS客队、胜平负、让球、总进球、半全场、双平、比分参考、各项赔率和 p、在售/过关状态、风险标签。窗口外和排除的比赛也显示，并注明原因。
   - 篮球赛程表：按早/晚场分组，**客队在前、主队在后**，列出胜负、让分（主队让分口径）、大小分的赔率和 p。
3. **比赛详情页**：该场全部市场的赔率、p_mkt、倒数和、23维证据表（来自 Agent 输出）、来源链接、六类方向命中情况。
4. **分析任务页**（admin）：“生成今日分析”“刷新赔率并复核”“复盘昨日”三个按钮，任务队列和状态（排队/运行/完成/失败）、实时日志、耗时、花费。
5. **历史与台账**：按日期查看历史报告；命中率台账分最终推荐、六类、八结构、梦想单统计。实际投注金额和返还固定为 null。
6. **体系文档页**：只读展示 V6 文档当前修订。

### 6. 分析引擎：调用 Claude Agent
- **使用本机已登录的 Claude Code 命令行**（`/Users/ycy/.local/bin/claude`，无头模式 `claude -p`），不使用 API Key。工作目录为 `/Users/ycy/ycy/foot`，让它自动加载 `AGENTS.md`。用 `--output-format stream-json` 实时记录日志，用 `--allowedTools` 限制可用工具，模型由 `--model` 配置【默认沿用本机设置】。后端用子进程调用，设超时，同一时间只运行一个分析任务（加文件锁），其余排队。命令行未登录或额度用尽时，任务标为失败并提示。
- 后端先完成确定性计算：抓取、p_mkt、候选和八结构枚举、2.5 门槛筛选，复用并模块化 `analyze.py` 的逻辑。然后把计算结果和当天赛程交给 Agent。Agent 负责：联网查伤停和首发等非赔率证据、按 20.3 节否决或降级、写每腿理由和反证、生成六类方向和梦想单、组织报告。
- Agent 输出必须是**结构化 JSON**（固定 schema：groups、legs、options、reasons、counter、withdraw、sources、six、dream、summary），外加 report.md。后端把 JSON 交给 `audit_recommendations.py` 审核：通过才标为“已发布”；不通过则标红显示失败项，并允许让 Agent 自动修正后重审（最多【2】次）。
- 允许 Agent 使用的工具：读写项目目录、Bash（受限）、WebSearch/WebFetch。禁止任何下单、投注或提交操作。每次运行限制最长时长【20分钟】和最大花费【可配置】。
- 每次运行保存：提示词、Agent 完整日志、输出 JSON 和 MD、审核结果、数据快照引用，形成不可覆盖的发布版本。同日再次运行生成新版本，旧版本标为“已替代”，不删除。
- 临场复核：开赛前刷新赔率。若任一入选腿停售、低于 1.33、组合跌破 2.5 或撤销条件触发，首页醒目提示“需复核”，可一键让 Agent 重新评估。

### 7. 两种触发方式：按钮和定时（都要支持）
- **按钮**：admin 在分析任务页点击“生成今日分析”“刷新赔率并复核”“复盘昨日”，立即入队执行，结果显示在前端。
- **定时**：后端内置调度（APScheduler），时间可在 admin 页修改，并持久化到 SQLite。默认：
  - 每天【11:30】生成今日分析；
  - 早场、中场、晚场首场开赛前各【60分钟】刷新赔率并复核；
  - 每天【09:30】复盘前一业务日。
- 按钮和定时跑的是同一套流程，产出同样的发布版本；版本记录里要标明触发来源（按钮+操作人，或定时）。

### 8. 钉钉消息推送（定时任务必须推送）
- **定时任务完成后**，结果既显示在前端，也**发送到用户的钉钉**。按钮触发默认不推送，页面上提供“推送到钉钉”按钮可手动推送。
- 推送方式：用复用应用的**工作通知**（`https://oapi.dingtalk.com/topapi/message/corpconversation/asyncsend_v2`，企业 token 用 gettoken 获取），需要配置 `DINGTALK_AGENT_ID`，并在钉钉开放平台为该应用开通“工作通知/消息通知”权限。接收人为 `FOOT_NOTIFY_USER_IDS`（默认等于 admin 白名单）。
- 消息格式用 markdown，内容就是“最终推荐汇总”：
  - 足球早中场①、足球晚场②、篮球早场、篮球晚场，每组两腿、赔率、命中估算、一句话理由、撤销条件；
  - 最后附梦想单；
  - 写明审核状态和数据快照时间；
  - 附系统详情链接 `http://172.16.37.247:5020/...`。
- 字数超出钉钉上限时，先发汇总，再附链接，不截断推荐腿。
- 复核任务只在发生变化时推送（入选腿停售、低于1.33、组合跌破2.5、撤销条件触发、推荐被替换），并醒目标出“需复核/已替换”。复盘任务推送当日命中结果和累计命中率。
- 审核不通过或任务失败也要推送失败通知，但不能把未通过审核的推荐当成正式推荐发出去。
- 推送结果（成功/失败、task_id、钉钉返回）写入日志，失败自动重试【3】次。

### 9. 复盘
- 每天定时（默认【09:30】）抓取前一业务日赛果，按原发布版本逐场结算（复用 `ledger_data/build_ledgers.py` 的结算逻辑），更新台账，必要时调用 Agent 写错误归因。

### 10. 不可违反的约束
- 只做研究和展示：不接入任何投注接口，不下单，页面写明“不保证命中或收益”。
- 不编造比赛、赔率、首发或概率；缺失就显示“待核/不可用”。
- 赔率、p、组合乘积用 Decimal 计算，显示时四舍五入（ROUND_HALF_UP）。
- 足球主队在前，比分为主:客；篮球客队在前，比分为客:主。
- 所有 shell 命令按项目规则以 `rtk` 开头（开发阶段）。

### 11. 交付物
- 新增目录 `web/`：`app.py`、`auth_service.py`、`data_fetch.py`、`engine/`（计算加 Agent 调用）、`templates/`、`static/`、`tests/`。
- `requirements.txt`、`.env.example`、`start.sh`（gunicorn）、launchd plist、`README_web.md`（本机部署、钉钉开放平台新增回调和开通工作通知的步骤、macOS 防火墙放行 5020、防休眠设置）。
- 测试：登录回调（mock 钉钉）、p_mkt 计算、2.5 门槛、审核脚本集成、权限拦截。先在本机 `127.0.0.1` 跑通，再给出服务器部署步骤。

### 12. 实施顺序
1. 骨架、钉钉登录、权限。
2. 数据抓取、赛程页（不含 Agent，仅显示赔率和 p）。
3. 计算模块化，接入审核。
4. Agent 分析任务、结构化输出、发布版本。
5. 复盘与台账页。
6. 定时任务、钉钉消息推送、临场复核提醒、launchd 部署和文档。

每个阶段完成后先运行测试并截图或用 curl 验证，再进入下一阶段。

---

## 已确认的决定（2026-11-04）
1. 部署在本机，默认端口 5020（`http://172.16.37.247:5020`）。
2. 复用 version_ctrl_console 的钉钉应用，只新增回调地址；发消息另需 `DINGTALK_AGENT_ID` 和工作通知权限。
3. 只有白名单里的人能登录。
4. 分析使用本机已登录的 Claude Code 命令行（`claude -p`），不用 API Key。
5. 按钮和定时两种触发都支持；定时任务结果既显示在前端，也推送到钉钉。

## 开工前还需要用户提供
- 已提供：CorpId `dingd90ed0515bd6b6a2`，已写入本地 `.env`（已加入 .gitignore，权限600）。
- 已提供并写入 `.env`：`DINGTALK_CLIENT_ID=dingrdyadgejla5pjli5`、`DINGTALK_AGENT_ID=5050803138`（来自截图文字，首次登录测试时校验）。
- 待用户在本机 `.env` 自行填写：`DINGTALK_CLIENT_SECRET`（开放平台只显示打码值，需点“查看”取完整值，或从服务器 `~/pix/vehicle_management_terminal/.env` 复制）。另需在钉钉开放平台新增回调地址并开通工作通知权限。
- userId 的获取方式：系统要提供“首次登录引导”。白名单为空或用户不在白名单时拒绝登录，但在拒绝页和日志里显示其钉钉 userId 和姓名，方便管理员复制进 `FOOT_ALLOWED_USER_IDS`。白名单为空时，任何人都不能进入系统。
