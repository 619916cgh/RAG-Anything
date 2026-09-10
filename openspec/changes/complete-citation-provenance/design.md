## Context

通用 RAG、Agentic、AutoRepair 和 Public Demo 目前存在多套引用结构。文本检索常以文档名或临时 `file_path` 追溯，视频另有 PostgreSQL 时间段，ODL 图片目录保留页码/元素/bbox，但这些信息没有统一绑定到最终 chunk 和持久化消息。旧规格还要求把完整路径发给客户端并通过操作系统打开文件，这与当前受控媒体和路径脱敏安全边界冲突。

本变更只保证新上传资料。历史资料没有可靠的 source hash、页码或元素身份时不得猜测，查询层返回文档级或 `legacy_unavailable` 降级。实现跨 PostgreSQL migration、Worker/解析器、检索、路由、消息存储与 React 展示，必须分别验证代码、迁移、Worker 和浏览器证据。

## Goals / Non-Goals

**Goals:**

- 建立从请求内 `[来源 N]` 到 `document_id + chunk_id + source_sha256` 的持久化 provenance 链。
- 在解析器确有证据时提供 1-based 页码、章节、图片元素/bbox/坐标系和视频时间/frame refs。
- 所有查询与持久化入口返回同一条路径无关 citation DTO，并用受控授权 URL 交付媒体。
- 对重复上传、同名文件、hash 变化、并发重建和删除/重试保持文档作用域隔离。
- 前端复用一个组件展示文本、图片和视频定位，并对缺失或失效信息明确降级。

**Non-Goals:**

- 不全量回填或重新解析历史资料。
- 不从 Markdown、Marker 或任意裸 `page_idx` 推断真实页码。
- 不把 bbox 存在本身表述为已具备整页预览；只有受控页面图像存在时才画叠加高亮。
- 不执行生产迁移、生产数据操作或生产发布。

## Decisions

### 1. 当前 provenance 使用逻辑 chunk 身份原子覆盖

`citation_provenance` 以 `(kb_name, document_id, chunk_id, provenance_version)` 作为唯一当前记录，`source_sha256` 是必须且可更新的内容身份。upsert 直接 `ON CONFLICT` 更新 source hash 与定位字段，不采用“删除旧 hash 后插入”的竞态流程。

选择单条当前记录而不是保留多个 hash 版本，是因为查询需要无歧义地把一次命中映射到当前索引。若未来需要历史审计，应另建 append-only history，而不是让查询从多条 current 中按时间猜测。

### 2. 页码只从明确契约转换

公开 `page` 固定为 1-based。ODL/PDF 明确给出 `source_page` 或声明 `page_index_base=0` 时，内部 `page_idx` 才能转换；其他解析器只有裸索引、标题或页码样式文本时保持 `page=null`。定位状态按证据从高到低为 `exact`、`page`、`document`、`unavailable`。

### 3. 多模态媒体身份必须对文档作用域化

图片沿用 ODL catalog 的 `media_id + element_id`，并继续由 catalog 校验 KB、document、chunk 和根目录。新视频的 asset identity 由 `kb_name + document_id + source_sha256 + profile` 派生；segment identity 还加入 asset scope 和时间范围。旧视频行保持可读，不回写历史 identity。

该选择避免相同字节文件上传到不同 KB 或 document 时争用全局 media/segment 主键，防止 owner 错绑、受控 URL 404 和删除级联。替代方案是 asset 与 document association 表，但会扩大既有 029 schema 的迁移和运行时复杂度，本轮采用新上传作用域 ID。

### 4. 检索请求内先编号，响应阶段再批量富化

native、RRF、Graph 和 tag-scoped 检索将有身份的命中注册到请求级 `provenance_sink`，按首次出现分配 `[来源 N]`，碰撞键为 `(document_id, chunk_id)`。LLM 只能原样复用已有编号。回答完成后，路由先从最终回答提取实际出现的有效数字 `[来源 N]`，按首次出现顺序过滤、去重并拒绝越界或伪造编号，再用一条批量查询获取这些编号对应的持久化 provenance 并构建 DTO；缺少新表记录时保留资料名和 excerpt，标记 `locator_status=unavailable`、`legacy_status=legacy_unavailable`。回答没有有效来源标记时不得把全部检索命中作为 citations 返回。

`provenance_sink` 不进入 execution scope 的 Mapping、比较、repr、缓存键或日志，避免检索内容进入元数据通道。无 document/chunk identity 的命中不得按同名文档猜测关联。

### 5. 公开 DTO 使用白名单并运行时生成授权 URL

公开字段固定为 citation/document/chunk 身份、excerpt、page、section、modality、定位状态，以及可选 image/video 子对象。`source_sha256`、`kb_name`、`file_path`、`server_path`、token 和原始 metadata 不进入 DTO。bbox、坐标系和 frame refs 使用深层字段白名单，不能原样透传嵌套对象。

数据库只保存 opaque media identity；认证 Agent/AutoRepair 在 KB 授权完成后生成 `/api/knowledge/media/...`，Public Demo 则替换为短期 share grant URL。客户端提供的 URL 或数据库路径不会被信任。

### 6. 所有终态与持久化结构一致

Agent 标准、ReAct、CoT、库存、retrieval-only 和 fallback 分支的 SSE `done` 均显式包含 `citations` 数组。实际产生回答的分支把相同列表写入 assistant message 和 query history；reload 直接恢复该列表。Public Demo 不持久化会话，但 done 事件使用同一 DTO。AutoRepair 继续保留已有兼容字段，同时内部与公开响应都经过统一规范化和授权。

### 7. 新写入和生命周期变更失败闭合

新上传任务只有在 provenance upsert 成功后才能报告对应索引写入成功。chunk、文档和 KB 删除必须传播非预期 PostgreSQL 错误，不能吞掉失败后继续报告业务删除成功；只有明确识别为迁移尚未安装的兼容场景，读取或旧部署清理才可按既定 legacy 规则降级。重试、取消和补偿清理必须保持文档作用域，不能删除其他 KB 或 document 的同内容媒体。

### 8. 展示以现有 chunk 详情和受控播放器为落点

`ProvenanceList/ProvenanceItem` 显示资料名、页码、章节、excerpt 和定位状态；登录用户通过 KB/document/chunk 路由打开现有详情，不再请求服务器用 OS 打开文件。视频复用 seek 到 `start_ms / 1000`。图片显示受控缩略图、图号/元素 ID；只有同时存在整页预览和可换算 bbox 时高亮，否则显示“页内图片”或页码级降级。

### 9. 新上传媒体使用 v2 完成契约

Worker 只在权威 doc-status、全部 chunk provenance、图片 catalog/counts 或视频 asset/segments 全部一致后写入 `media_delivery_version=2`。v2 文档不得回退到进程内 legacy grant；视频公共 DTO 的顶层及每个 segment 均携带稳定 `media_id + media_kb`，媒体 URL 在响应时派生。视频交付还会重新计算文件摘要，文件被替换、删除或失去当前 owner 绑定时统一返回 404。旧文档和旧会话不回填、不重签，继续按既有 legacy 降级路径读取。

## Risks / Trade-offs

- **Parser 信息不完整** -> 保持 nullable 字段和显式 `unavailable`，不以展示完整度驱动伪造数据。
- **新增表未迁移时查询失败** -> 读取 fail-soft 为 legacy DTO；新上传写入和删除写操作 fail closed，避免任务成功但 provenance 丢失。
- **检索后 LLM 未正确复用编号** -> 只返回最终回答实际复用且能在 sink 中解析的编号；无有效编号返回空数组，不按文档名或全部命中二次猜测。
- **历史视频全局 media ID 仍存在** -> 历史资料只读兼容；文档作用域 ID 仅用于新上传，不做高风险数据重写。
- **整页预览缺失** -> bbox 仍可存储和展示数值，但不在错误背景上画高亮。
- **前端兼容多套旧字段增加复杂度** -> normalization 工具集中处理旧结构，新增后端只输出统一 DTO。

## Migration Plan

1. 在候选代码中注册并验证 038 migration；不对现有数据库直接执行。
2. 后端、Worker 和前端作为同一候选发布，迁移先于接受新 provenance 上传。
3. 新上传任务写入 provenance；旧资料查询自动返回 legacy 降级，不启动回填。
4. 在隔离 PostgreSQL 验证 fresh、upgrade、repeat、故障记录/恢复、并发 hash 替换和同内容跨 KB/document 隔离。
5. 使用新上传 PDF、图片文档和视频完成同一 Run 的 Worker + PostgreSQL + 浏览器验收，并验证删除与 reload。
6. 回滚应用时保留 additive 038 表；旧应用忽略该表。只有经独立备份/恢复评审后才考虑移除数据，不在普通回滚中 drop。

## Open Questions

- ODL 当前未保证产生受控整页预览，因此 bbox 浏览器验收默认允许“坐标可核对但无叠加背景”的降级；未来若新增页面渲染目录，需要单独定义其生命周期和授权契约。
