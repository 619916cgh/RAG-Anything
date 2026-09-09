# conversation-summary-compression (Delta)

## MODIFIED Requirements

### Requirement: 摘要触发条件

系统 SHALL 在对话消息数超过配置阈值时，触发生成对话摘要。

#### Scenario: 首次触发生成摘要

- **WHEN** 智能体会话的消息数首次超过 `CONVERSATION_SUMMARY_TRIGGER_ROUNDS * 2` 条（默认 20 条，即 10 轮）
- **AND** `CONVERSATION_SUMMARY_ENABLED=true`（默认启用）
- **THEN** 系统在本次响应完成后，异步调用 LLM 将早期消息压缩为摘要
- **AND** 摘要文本存储到 `agent_conversations.summary` 字段
- **AND** `summary_updated_at` 更新为当前时间
- **AND** 压缩比校验依照 `conversation-compression-ratio` 规范执行

#### Scenario: 摘要注入模型上下文

- **WHEN** 会话已有非空 `agent_conversations.summary`
- **AND** 查询不是 `retrieval_only`，且摘要功能启用
- **THEN** 普通 RAG、ReAct 和 CoT 路径 MUST 将摘要作为独立上下文层注入
- **AND** 摘要层 MUST 位于近期消息层之前
- **AND** 摘要为空或功能关闭时，系统 MUST 保持现有纯近期历史行为

### Requirement: 摘要相关配置

系统 SHALL 通过环境变量控制摘要功能的行为。

#### Scenario: 环境变量列表

- **WHEN** 系统启动
- **THEN** 读取以下环境变量：
  - `CONVERSATION_SUMMARY_ENABLED`：是否启用摘要功能，默认 `true`
  - `CONVERSATION_SUMMARY_TRIGGER_ROUNDS`：触发摘要的最小对话轮数，默认 `10`
  - `CONVERSATION_SUMMARY_MAX_TOKENS`：用于摘要 Prompt 注入的最大 token 数，默认 `1000`
  - `CONVERSATION_SUMMARY_LLM_MODEL`：用于摘要生成的 LLM 模型，默认为主模型

#### Scenario: 默认值

- **WHEN** 上述环境变量未设置
- **THEN** 使用默认值：`CONVERSATION_SUMMARY_ENABLED=true`，`CONVERSATION_SUMMARY_TRIGGER_ROUNDS=10`，`CONVERSATION_SUMMARY_MAX_TOKENS=1000`
