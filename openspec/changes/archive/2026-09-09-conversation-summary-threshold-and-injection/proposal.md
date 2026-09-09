## Why

会话摘要默认在第 4 轮完整问答后就开始异步生成，过早增加了无意义的 LLM 调用；同时已生成并持久化的摘要没有从会话线程读回 Prompt，因此摘要压缩功能当前实际不参与模型上下文。

## What Changes

- 将 `CONVERSATION_SUMMARY_TRIGGER_ROUNDS` 默认值从 3 调整为 10，使首次摘要等待超过 20 条消息后再异步生成。
- 在普通 RAG、ReAct 和 CoT 路径读取 `agent_conversations.summary`，并按摘要优先于近期历史的顺序注入模型上下文。
- `retrieval_only`、库存回答、新线程、空摘要或显式关闭摘要时保持纯近期历史行为。
- 更新环境变量示例、OpenSpec 主规格和定向回归测试；无数据库迁移或公开 API 变更。

## Capabilities

### New Capabilities

<!-- 无新能力 -->

### Modified Capabilities

- `conversation-summary-compression`: 默认触发阈值与摘要 Prompt 注入行为对齐近期对话窗口。

## Impact

- 后端：`raganything/routers/agent.py` 的摘要生成阈值与三类回答路径 Prompt 构造。
- 运维：`.env.example` 默认配置说明；现有显式环境变量继续优先。
- 测试与文档：摘要压缩阈值测试、agent stream 注入回归、OpenSpec 规格。
- 无前端、HTTP/SSE 字段、依赖、RBAC 或数据库 schema 变更。
