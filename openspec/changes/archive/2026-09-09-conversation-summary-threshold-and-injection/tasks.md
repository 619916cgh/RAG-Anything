## 1. 摘要默认阈值

- [x] 1.1 `_maybe_generate_summary` 的 `CONVERSATION_SUMMARY_TRIGGER_ROUNDS` 默认值从 3 调整为 10

## 2. 摘要 Prompt 注入

- [x] 2.1 请求上下文提取已持久化摘要，摘要显式关闭时不读取
- [x] 2.2 普通 RAG 路径调用 `PromptBuilder.add_summary`
- [x] 2.3 ReAct 路径把摘要传入 `_build_layered_query`
- [x] 2.4 CoT 路径在 `## 对话历史` 前注入 `## 对话摘要`

## 3. 配置与规格

- [x] 3.1 更新 `.env.example` 默认说明
- [x] 3.2 更新主规格默认值说明
- [x] 3.3 创建本 OpenSpec change delta

## 4. 测试与收尾

- [x] 4.1 更新摘要触发默认测试：20 条不触发、22 条触发、显式 3 轮仍生效
- [x] 4.2 在 RAG/ReAct/CoT stream 测试中验证已持久化摘要进入最终 prompt
- [x] 4.3 运行定向 pytest、Python 编译和 diff check
- [x] 4.4 更新 `PROJECT_SUMMARY.md` 近期任务记录
