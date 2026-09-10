## ADDED Requirements

### Requirement: 新上传 chunk 的 provenance 持久化

系统 SHALL 为迁移启用后成功入库的新上传资料建立 `citation_provenance` 当前映射，并以 `(kb_name, document_id, chunk_id, provenance_version)` 作为唯一逻辑身份。`document_id`、`chunk_id` 和完整 `source_sha256` SHALL 为必填防串联字段，写入 SHALL 使用原子 upsert 更新当前记录。

#### Scenario: fresh upgrade repeat migration
- **WHEN** 038 migration 分别在空数据库、已有 037 schema 的数据库和已应用 038 的数据库执行
- **THEN** fresh 与 upgrade MUST 建立同一约束和索引
- **AND** repeat MUST 为无变更成功且 migration history 保持一致

#### Scenario: 并发 hash 替换只有一条 current
- **WHEN** 两个写入并发更新同一 KB、document、chunk 和 provenance version，但携带不同 source hash
- **THEN** 数据库 MUST 只保留一条 current 记录
- **AND** 该记录的 hash 与全部 locator 字段 MUST 来自一次完整原子 upsert，不得混合两次写入

#### Scenario: 同名和重复上传不串联
- **WHEN** 同名文件具有不同 source hash，或同内容文件上传到不同 KB/document
- **THEN** provenance MUST 依照 KB、document、chunk 和 source hash 命中正确记录
- **AND** 不得仅按文档名、chunk 文本或全局 source hash 关联

### Requirement: 新资料启用与历史资料降级

系统 SHALL 只保证迁移启用后新上传资料的完整 provenance，不对历史资料自动回填或猜测定位。

#### Scenario: 新上传媒体完成契约
- **WHEN** Worker 准备将新上传文档标记为完成
- **THEN** 系统 MUST 从权威 doc-status 按 task identity 唯一解析文档
- **AND** 全部 declared chunk MUST 具有同 document 和 source hash 的 provenance
- **AND** 图片 catalog/counts 或视频 asset/segments/实际源文件 MUST 与 provenance 完整一致
- **AND** 只有通过审计后才写入 `media_delivery_version=2`

#### Scenario: v2 媒体不使用 legacy grant
- **WHEN** v2 文档的媒体 catalog 未命中或绑定失效
- **THEN** 系统 MUST fail closed
- **AND** MUST NOT 签发、持久化或返回 `legacy_grant`、`legacy:*` 或 legacy 媒体 URL

#### Scenario: 新上传写入失败闭合
- **WHEN** 新上传 chunk 的 provenance 持久化失败
- **THEN** Worker MUST 将对应入库流程标记为失败或可重试失败
- **AND** 不得报告完整 provenance 已成功建立

#### Scenario: 历史 chunk 无映射
- **WHEN** 查询命中没有 `citation_provenance` 记录的历史 chunk
- **THEN** citation MUST 保留可证明的资料名和摘录
- **AND** `locator_status` MUST 为 `unavailable`
- **AND** `legacy_status` MUST 为 `legacy_unavailable`

### Requirement: 页码和 bbox 只来源于可信解析契约

系统 SHALL 对外使用 1-based 页码，并且只在解析器明确提供 `source_page` 或声明 page index base 时转换内部索引。未知页码、非法 bbox 或不完整坐标系 SHALL 保持空值或降级，不得推测。

#### Scenario: ODL 可信页码和 bbox
- **WHEN** ODL 元素提供可信页索引、元素身份、raw bbox、坐标原点、单位和页面尺寸
- **THEN** provenance MUST 保存 1-based page、element ID、figure label、bbox 与坐标系
- **AND** 公开 bbox MUST 转换为白名单 `x/y/width/height` 结构

#### Scenario: 非 ODL 页码未知
- **WHEN** Markdown、Marker 或其他解析器只提供未声明基准的裸 `page_idx`
- **THEN** 公开 `page` MUST 为 `null`
- **AND** 系统 MUST NOT 将该索引伪装为真实页码

#### Scenario: bbox 证据不完整
- **WHEN** bbox 无法验证边界、坐标原点、单位或页面尺寸
- **THEN** locator MUST 降级为 page、document 或 unavailable
- **AND** 前端不得绘制精确高亮

### Requirement: 多模态 provenance 使用文档作用域身份

系统 SHALL 将图片通过 `media_id + element_id` 绑定到文档 chunk，并为新视频使用包含 KB、document、source hash 和 profile 的 asset identity；segment identity SHALL 包含该 asset scope、时间范围和 profile。

#### Scenario: 同视频跨 KB 和 document 隔离
- **WHEN** 相同视频字节上传到两个 KB 或同一 KB 的两个 document
- **THEN** 新建的 video asset 和 segment identity MUST 不同
- **AND** 查询、受控媒体授权和删除 MUST 只作用于各自 owner

#### Scenario: 视频重试幂等
- **WHEN** 同一 document 的同一视频任务以相同 profile 重试
- **THEN** asset 和 segment identity MUST 保持稳定
- **AND** upsert MUST 不产生重复 segment

#### Scenario: 图片元素关联
- **WHEN** 图片 chunk 具有 ODL media catalog 的 media ID 和 element ID
- **THEN** citation MUST 能恢复资料页码、图号或元素 ID
- **AND** 受控 URL MUST 在运行时经当前 KB/document 授权生成

### Requirement: provenance 生命周期清理失败闭合

系统 SHALL 在 chunk 替换、chunk 删除、文档删除、批量删除、任务取消/重试补偿和 KB 删除时按相同 KB/document scope 清理 provenance；非预期数据库错误 MUST 传播到业务操作。

#### Scenario: 删除数据库失败
- **WHEN** provenance 或关联媒体删除遇到连接、约束或事务错误
- **THEN** 上层 mutation MUST NOT 报告成功
- **AND** 错误 MUST 以脱敏形式传播或记录供重试

#### Scenario: 未迁移环境的精确兼容
- **WHEN** 旧部署明确因 provenance 表不存在而执行 legacy 读取或兼容清理
- **THEN** 系统 MAY 降级为空映射或 legacy unavailable
- **AND** 不得把其他 PostgreSQL 异常当作表不存在吞掉

#### Scenario: 删除一个 owner 不影响另一个 owner
- **WHEN** 两个 document 上传了相同内容且删除其中一个 document
- **THEN** 另一个 document 的 provenance、video asset、segments 和受控媒体 MUST 保持可用
