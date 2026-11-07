# 022 项目Harness模型选择pixmoving

用户明确选择pixmoving / gpt-6.1-sol，OpenAI Chat Completions，API base https://api.pixmoving.net/v1。Issue #12。

仅项目harness-research.patch.yml覆盖agent-default-model provider/model，不修改全局profile或凭证；已有route及模型目录只读核实，引用存在不等于可用密钥。模型输入会发指定提供方，用户已确认小JSON测试，无赛事/聊天内容。失败fail closed，不回退其他模型/CLI，不复制当前GUI密钥。

验证组合选中正确route/model，真实无工具JSON、工具能力分开检查；缺凭证或网络如实记录，不夸大。网页搜索认证仍独立，不将OpenAI聊天baseURL当搜索Messages端点。
