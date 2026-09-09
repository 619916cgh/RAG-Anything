## Why

当前知识库引用只在部分查询链路保留文档名或视频时间，页码、图片元素、坐标和持久化消息之间没有统一且防串联的来源身份。新上传资料需要建立一条可验证、可降级且不暴露服务器路径的 provenance 链，使回答中的稳定编号能够回溯到具体文档、chunk、页面、图片或视频片段。

## What Changes

- 为新上传资料新增 PostgreSQL `citation_provenance` 映射，以 `kb_name + document_id + chunk_id + provenance_version` 作为当前记录的逻辑身份，并用 `source_sha256` 防止重复上传、重建索引和同名文件串联。
- 在 ODL 文档、普通文本、多模态图片和视频分段入库时持久化可信页码、章节、元素、bbox、坐标系、时间范围和 frame refs；历史资料不全量回填，统一降级为 `legacy_unavailable`。
- 定义统一、路径无关的 citation DTO 和 `exact/page/document/unavailable` 定位状态；公开响应只允许受控媒体 URL，不返回本地路径、token、source hash 或嵌套私有字段。
- 将请求内 `[来源 N]` 稳定绑定到 `document_id + chunk_id`，并统一 Agent 标准、ReAct、CoT、tag-scoped、RRF、Graph、LightRAG 原生、AutoRepair 和 Public Demo 的引用行为。
- 所有响应分支显式返回 `citations` 数组，并在 SSE `done`、助手消息、查询历史和会话 reload 间保持同一结构。
- 新增可复用 provenance 前端组件，展示资料名、页码、章节、摘录、图片元素/bbox 和视频时间，跳转现有 chunk 详情，并在定位或受控媒体不可用时明确降级。
- **BREAKING**：废止公开 citation DTO 和前端“打开本地文件”流程中的 `file_path` 契约；文件路径仅可作为服务器内部检索元数据存在，客户端改用文档/chunk 身份与授权媒体路由。

## Capabilities

### New Capabilities

- `citation-provenance`: 新上传资料的持久化、文档作用域、多模态 provenance 身份、定位精度、生命周期和验收契约。

### Modified Capabilities

- `citation-source-tracing`: 将公开追溯从完整文件路径改为 `document_id + chunk_id` 和路径无关的显示信息，并要求同名/重复资料不串联。
- `citation-structured-output`: 统一 citation DTO、数字来源映射以及非流式、SSE、历史、reload、AutoRepair 和 Public Demo 的响应结构。
- `citation-frontend-display`: 使用文档/chunk 详情和受控媒体展示来源，增加页码、图片位置、视频时间及不可定位降级，移除客户端本地文件打开依赖。

## Impact

- PostgreSQL migration manifest、provenance 服务、Worker/文档/多模态/视频入库与删除清理。
- LightRAG native、RRF、Graph、tag-scoped 和 Agentic 查询管线，Agent/AutoRepair/Public Demo 路由及消息持久化。
- AgentChat/Public Demo 引用展示、受控媒体播放器和 provenance 前端工具。
- 需要后端/前端聚焦回归、隔离 PostgreSQL migration 并发/故障测试，以及新上传 PDF、图片文档和视频的真实 Worker + PostgreSQL + 浏览器验收；这些证据与单元测试、构建和健康检查分别报告。
