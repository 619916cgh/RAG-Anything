## MODIFIED Requirements

### Requirement: ScoredChunk 包含源文档追溯字段

`ScoredChunk` 数据结构 SHALL 在服务器内部携带稳定的 `document_id`、`chunk_id`、可显示 `document_name` 和可选 `chunk_index`，并可携带仅供内部解析使用的路径元数据。公开 citation SHALL 使用文档/chunk 身份和授权媒体 URL，不得返回服务器完整路径。

#### Scenario: RRF 查询模式下 chunk 携带源信息
- **WHEN** 系统通过 RRF 混合检索模式执行查询
- **THEN** 每个可追溯 `ScoredChunk` MUST 包含源 `document_id` 和 `chunk_id`
- **AND** `document_name` MUST 包含可显示的文档名称
- **AND** 公开响应 MUST NOT 包含服务器完整路径

#### Scenario: Graph 查询模式下 chunk 携带源信息
- **WHEN** 系统通过知识图谱查询模式执行查询
- **THEN** 每个可追溯 `ScoredChunk` 的 document/chunk 身份 MUST 被正确填充
- **AND** 无稳定身份的命中 MUST 保持不可定位而非按文档名猜测

#### Scenario: LightRAG 原生模式下 chunk 携带源信息
- **WHEN** 系统通过 LightRAG 原生查询模式执行查询
- **THEN** 结果包装层 MUST 通过 chunk identity 查询 doc status 和 provenance 后填充可证明的源信息

#### Scenario: tag scoped 模式保留源身份
- **WHEN** 系统对标签过滤后的 native、RRF 或 Graph 结果构造上下文
- **THEN** tag-scoped 结果 MUST 使用与非标签查询相同的 document/chunk 身份契约

### Requirement: 源文档信息查询接口

系统 SHALL 提供通过 `document_id + chunk_id` 批量查询源文档和 provenance 的服务器内部接口，以减少数据库访问次数并避免同名文件或跨文档 chunk 串联。

#### Scenario: 单个 document chunk 查询
- **WHEN** 传入有效的 document ID 和 chunk ID
- **THEN** 系统 MUST 返回可显示文档名和已有 locator 信息
- **AND** 未找到时 MUST 返回不可定位结果而非抛出未处理异常

#### Scenario: 批量 document chunk 查询
- **WHEN** 传入多个 document/chunk identity
- **THEN** 系统 MUST 在有界批量查询中返回所有可解析映射
- **AND** 无法解析的 identity MUST 在结果中标记为未找到而非按文档名补配

#### Scenario: 同名文档隔离
- **WHEN** 两个 document 使用相同文件名且 chunk 文本相同
- **THEN** 查询 MUST 依赖 document/chunk identity 和 source hash fencing 返回正确 owner
- **AND** 不得暴露内部 `file_path`、`server_path` 或 source hash
