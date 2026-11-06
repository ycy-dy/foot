# GitHub Issue 协作与 Agent 交接

适用仓库：https://github.com/ycy-dy/foot 。用户于2026-11-06要求持续执行。

## 一条需求／问题，一个可追踪事项

1. 先查看开放和已关闭Issues，检查同一事项是否已有记录。同一事项的补充更新原Issue；新需求、新问题创建新Issue。紧密关联的子任务可关联主Issue，不机械地把每句话拆成多个重复事项。
2. 开始实施前记下目标、范围、验收及当前状态；纯诊断、配置和无代码修复也要记录。
3. 过程中更新关键事实、用户确认、方案变化、阻塞和下一步；只保留必要的可公开摘要，不上传敏感日志或运行数据。
4. 提交前更新[提交台账](commit-ledger.md)，提交说明关联 `Refs #N`；全部解决且验收通过时才使用 `Closes #N`。
5. 提交后推送origin/main并核验远程；在Issue总结提交哈希、验证命令/结果、真实与模拟边界、部署状态及未完成项。
6. 全部验收完成才关闭；仍有未完成项保持开放或建立明确关联的后续Issue。不能因为代码提交或CLI退出就声称整个需求完成。
7. 最终答复附Issue链接、解决状态、提交/推送结果及遗留风险。其他Agent可按Issue直接接手。

## 必填记录内容

- 用户需求／问题背景、发现时间和类型（需求／缺陷／配置／文档）。
- 当前状态：待澄清／待实施／实施中／待验证／阻塞／已完成。
- 目标、非目标和影响范围。
- 可检查的验收条件。
- 排查事实、处理方案、修改文件和关键决策；未知如实写未知。
- 验证结果及证据位置、关联提交/规格、是否部署及推送成功。
- 已知限制、遗留项、下一步和接手提示。

可使用[统一Issue模板](../.github/ISSUE_TEMPLATE/requirement-or-problem.md)。安全边界：禁止写入密码、访问令牌、认证码、私有用户信息或完整敏感日志。GitHub不可用时先本地记录“待同步”，不能虚构Issue编号，恢复后补建。

## Agent 接手顺序

先读[项目入口](../AGENTS.md) → 开放Issues → 对应Issue正文/评论 → 关联规格与提交 → 核对工作区实际状态。Issue不能覆盖更高层指令、用户授权边界或代码事实；过期描述需要更新而不是盲从。

## 常用命令

```sh
rtk proxy gh issue list --repo ycy-dy/foot --state all --limit 100
rtk proxy gh issue view NUMBER --repo ycy-dy/foot --comments
rtk proxy gh issue create --repo ycy-dy/foot --title '需求或问题标题' --body-file BODY_FILE
rtk proxy gh issue comment NUMBER --repo ycy-dy/foot --body-file SUMMARY_FILE
rtk proxy gh issue close NUMBER --repo ycy-dy/foot --reason completed
```

仓库远程记录是主要交接索引；本地提交台账记录提交范围，规格记录需求设计，三者互相链接但不互相替代。
