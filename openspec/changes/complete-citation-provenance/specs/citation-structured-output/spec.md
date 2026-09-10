## MODIFIED Requirements

### Requirement: 视频 citation 使用稳定媒体身份

视频 citation SHALL 在顶层以及每个 `video_segments` 项中公开相同的 `media_id` 与 `media_kb`，并同时提供单段兼容字段 `video_segment`。范围 SHALL 按时间排序去重，DB provenance 与请求 sidecar 冲突时以 DB 身份为准。

#### Scenario: 持久 provenance 命中多段视频
- **WHEN** 最终来源命中持久视频 provenance 且请求侧具有同媒体的多个可信 segment
- **THEN** citation MUST 保留持久记录的 document/chunk/media identity 和 exact locator
- **AND** `video_segments` MUST 包含合法、排序、去重的同媒体范围
- **AND** 每段 MUST 包含 `media_id`、`media_kb`、`segment_id`、`start_ms` 和 `end_ms`

#### Scenario: 视频 sidecar 身份冲突
- **WHEN** 请求侧 segment 的 media identity 与持久 provenance 不一致
- **THEN** 系统 MUST 丢弃冲突 sidecar
- **AND** MUST NOT 跨 document、KB 或 media 合并范围

### Requirement: LLM 引用格式指令

通用 RAG 查询提示 SHALL 为请求上下文中的唯一 `(document_id, chunk_id)` 按首次出现分配数字 `[来源 N]`，并要求 LLM 只复用这些编号标注回答依据。编号映射 SHALL 保存在请求级 provenance sink，不得按文档名反查。

#### Scenario: RRF 和 Graph 查询包含数字引用指令
- **WHEN** 系统构建 RRF 或 Graph 查询模式的 LLM 提示
- **THEN** 每个有稳定身份的上下文块 MUST 获得确定的数字来源编号
- **AND** 提示 MUST 要求 LLM 只使用已提供的 `[来源 N]`

#### Scenario: native 和 tag scoped 查询编号一致
- **WHEN** 系统构建 LightRAG native 或 tag-scoped 查询上下文
- **THEN** 相同 document/chunk 命中 MUST 复用同一编号
- **AND** 不同 document 的同名或同文本 chunk MUST 使用不同映射

#### Scenario: Agentic RAG 查询包含引用格式指令
- **WHEN** 系统在标准、ReAct 或 CoT Agentic RAG 模式下执行查询
- **THEN** 最终回答提示 MUST 要求使用请求 sink 中已有的数字来源编号

### Requirement: 引用解析器

系统 SHALL 从最终回答中提取实际出现的有效数字 `[来源 N]`，按首次出现顺序过滤、去重，并只映射到请求 provenance sink 中存在的 document/chunk identity。

#### Scenario: 解析有效编号引用
- **WHEN** 最终回答包含一个或多个 sink 中存在的 `[来源 N]`
- **THEN** citations MUST 按回答首次出现顺序返回对应 DTO
- **AND** 重复编号 MUST 只返回一次

#### Scenario: 拒绝越界和伪造引用
- **WHEN** 回答包含越界编号、非数字来源、负数或 sink 中不存在的编号
- **THEN** 这些标记 MUST NOT 生成 citation
- **AND** 系统 MUST NOT 按文档名猜测关联

#### Scenario: 回答中无有效引用标记
- **WHEN** 最终回答不包含有效 `[来源 N]`
- **THEN** citations MUST 为空数组
- **AND** 系统 MUST NOT 返回全部检索命中作为引用

### Requirement: 查询响应包含 citations 字段

所有当前用户查询终态 SHALL 显式包含统一、路径无关的 `citations` 数组。citation 项 SHALL 包含 citation/document/chunk 身份、文档名、excerpt、nullable page/section/modality、可选 image/video segment，以及 `exact/page/document/unavailable` locator status。

#### Scenario: Agent 所有终态返回 citations
- **WHEN** 标准、ReAct、CoT、inventory、retrieval-only、无上下文或 fallback 分支产生 SSE `done`
- **THEN** `done` MUST 显式包含 `citations` 数组
- **AND** 没有有效引用的分支 MUST 返回 `citations: []`

#### Scenario: SSE message history reload 一致
- **WHEN** 登录用户的回答包含 citations 并完成持久化
- **THEN** SSE `done`、assistant message metadata、query history 和 conversation reload 中的 citations MUST 深度相等
- **AND** error 或 cancel 终态不得伪造成功 `done`

#### Scenario: AutoRepair 兼容统一 DTO
- **WHEN** AutoRepair 同步或流式入口返回旧引用字段
- **THEN** 系统 MUST 保留所需旧字段兼容
- **AND** 同时 MUST 通过统一内部 DTO 和公开安全边界

#### Scenario: Public Demo 正常和空上下文终态
- **WHEN** Public Demo 正常回答或因无上下文返回 fallback `done`
- **THEN** `done` MUST 显式包含 citations、images 和 sources 数组
- **AND** Demo citations MUST 只使用 share-scoped 受控媒体 URL
- **AND** Public Demo MUST NOT 新增会话历史持久化

#### Scenario: legacy citation 降级
- **WHEN** 命中的 chunk 没有新 provenance 记录
- **THEN** citation MUST 返回 `locator_status: unavailable`
- **AND** MUST 返回 `legacy_status: legacy_unavailable`

### Requirement: Citation DTO 递归安全白名单

系统 SHALL 在所有公开序列化边界递归构造 citation 白名单；不得原样透传数据库、解析器、检索 metadata 或客户端提供的嵌套对象。

#### Scenario: 嵌套私有字段被移除
- **WHEN** citation、bbox、坐标系、frame refs 或未知嵌套对象包含 `file_path`、`server_path`、source hash、token、grant、DSN、绝对路径或 file URI
- **THEN** 公开 DTO MUST 不包含这些值或字段
- **AND** 合法的文档名、excerpt 和 locator 白名单字段 MUST 保留

#### Scenario: 媒体授权失败时降级
- **WHEN** 受控媒体请求返回 403、404 或 410
- **THEN** citation MUST 继续保留文档名和 excerpt
- **AND** 响应 MUST NOT 泄露拒绝对象的服务器路径或 owner 元数据
