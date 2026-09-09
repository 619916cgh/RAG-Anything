## Context

当前 `_maybe_generate_summary` 默认 trigger 为 3 轮，即超过 6 条消息后开始生成；在每次完整问答落库后调用，所以正常对话实际在第 4 轮结束、8 条消息时首次触发。与此同时，摘要仓库函数已具备读写能力，但 `agent_query_stream` 只在上下文中提取最近消息，没有读取线程的 `summary` 字段，也没有在普通 RAG、ReAct、CoT 的 Prompt 构造中注入。

## Goals / Non-Goals

**Goals:**

- 避免 10 轮近期消息窗口内过早、重复地调用摘要 LLM。
- 让已生成摘要真正进入模型上下文，且摘要层位于近期历史之前。
- 保留显式环境变量覆盖和纯近期历史降级行为。

**Non-Goals:**

- 不修改 `agent_messages`、`agent_conversations` schema 或公开 API。
- 不追踪“哪条消息已进入摘要”，近期历史仍取最近 10 轮，允许与摘要重叠。
- 不重写摘要增量生成时使用完整消息列表的既有语义差异。

## Decisions

### 默认触发阈值

默认 `CONVERSATION_SUMMARY_TRIGGER_ROUNDS` 从 3 改为 10。现有判断为 `消息数 > trigger_rounds * 2`，因此默认首次摘要在 20 条之后、第 11 轮完整问答完成后异步触发，避免在第 4 轮就生成摘要。

### 摘要读取与注入

在非 `retrieval_only` 请求中读取 `conv_thread["summary"]`；摘要关闭时直接视为空。普通 RAG 使用 `PromptBuilder.add_summary`，ReAct 复用 `_build_layered_query` 的既有 `summary_text` 参数，CoT 在图片/历史上下文前增加独立摘要段。摘要为空或功能关闭时不改变现有行为。

## Risks / Trade-offs

- [摘要与最近 10 轮原始消息重叠] -> 保留重叠以最小化实现范围；模型可同时获得压缩记忆和近期原文。
- [长会话在摘要生成前继续增长] -> 摘要阈值默认对齐 10 轮窗口，显式配置可调低。
- [异步摘要生成晚于下一次请求] -> 沿用现有降级，下一次请求使用已有摘要或 NULL，不阻塞。

## Migration Plan

无需数据库迁移。发布为代码和配置说明变更；显式 `.env` 配置优先于代码默认值。

## Open Questions

无阻塞项。
