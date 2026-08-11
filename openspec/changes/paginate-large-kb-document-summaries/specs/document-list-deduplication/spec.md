## MODIFIED Requirements

### Requirement: 文档列表去重

系统 SHALL 在 `list_documents` API 响应中对同一逻辑文档只返回一条记录。分页摘要 API SHALL 对相同的展示文件名应用相同的去重规则，并以稳定的更新时间和文档 ID 排序后切页。
当 `processing_tasks`（内存）和 `kv_store_doc_status`（磁盘）中存在指向同一原始文件的条目时，系统 SHALL 合并为单一文档条目。

#### Scenario: 上传中的文档去重

- **WHEN** 文档正在上传处理中，`processing_tasks` 中有 `file: "测试.docx"` 的任务记录
- **AND** `kv_store_doc_status` 中存在 `file_path: "abc12345_测试.docx"` 的历史记录
- **THEN** `list_documents` 只返回一条文档记录，优先显示处理中的任务状态

#### Scenario: 已完成文档去重
- **WHEN** 文档处理已完成，`processing_tasks` 中的任务状态为 `completed`
- **AND** `kv_store_doc_status` 中存在对应的 `file_path` 条目
- **THEN** `list_documents` 只返回一条文档记录，状态为已完成
- **AND** 已完成的 `processing_tasks` 条目在本次响应后不被再次返回

#### Scenario: 摘要分页保持去重边界
- **WHEN** 调用者跨多个页面读取同一知识库的文档摘要
- **THEN** 同一去重后的逻辑文档 SHALL 至多出现在一个页面中
