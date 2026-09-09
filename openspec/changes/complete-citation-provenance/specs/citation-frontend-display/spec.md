## MODIFIED Requirements

### Requirement: 引用来源展示面板

前端消息展示 SHALL 通过可复用 `ProvenanceList/ProvenanceItem` 渲染每条 AI 回答的引用，显示资料名、1-based 页码、章节、原文摘录、图片或视频 locator 以及明确的不可定位状态。

#### Scenario: 回答包含引用时展示面板
- **WHEN** AI 回答的 `citations` 字段包含至少一条引用
- **THEN** 回答下方 MUST 显示引用来源区域
- **AND** 每项 MUST 显示可用的资料名、页码、章节和 excerpt

#### Scenario: 回答不包含引用时不展示面板
- **WHEN** `citations` 为空或不存在
- **THEN** 回答下方 MUST NOT 显示空引用列表

#### Scenario: 不可定位和 legacy 降级
- **WHEN** citation 的 page、bbox 或 provenance 记录不可用
- **THEN** 前端 MUST 显示文档级、页内图片或不可定位提示
- **AND** MUST NOT 伪造页码或坐标

### Requirement: 引用内联标记渲染

AI 回答文本中的有效 `[来源 N]` 标记 SHALL 与统一 citations 列表关联并渲染为可操作的内联引用；无对应 citation 的伪造或越界标记 SHALL 保持普通文本或不可操作状态。

#### Scenario: Markdown 中的有效引用标记可定位
- **WHEN** 回答文本包含与 citations 对应的 `[来源 1]`
- **THEN** 前端 MUST 将其渲染为可操作引用
- **AND** 操作后 MUST 聚焦对应 provenance 项

#### Scenario: 引用标记不影响正常 Markdown 渲染
- **WHEN** 回答同时包含引用和加粗、列表、链接或代码块
- **THEN** 标准 Markdown MUST 正常渲染
- **AND** 只有可解析的来源标记参与引用交互

### Requirement: 源文档跳转

引用条目 SHALL 仅在具有 `document_id + chunk_id` 且当前用户有权访问时跳转到现有文档 chunk 详情；客户端 SHALL NOT 将服务器路径发送到本地文件打开端点。

#### Scenario: 点击文档 chunk 定位
- **WHEN** 用户点击具有有效 document/chunk identity 的来源或上下文操作
- **THEN** 前端 MUST 导航到当前 KB 的文档 chunk 详情
- **AND** MUST NOT 调用 OS 打开服务器本地文件

#### Scenario: 缺少身份时保留摘录
- **WHEN** citation 缺少 document ID、chunk ID 或访问权限
- **THEN** 跳转操作 MUST 不可用或显示受控降级提示
- **AND** 已缓存文档名和 excerpt MUST 继续显示

### Requirement: 图片和视频定位展示

前端 SHALL 使用授权媒体 URL 展示图片缩略图和视频片段，并依据 locator 证据选择精确、页级或文档级展示。

#### Scenario: 视频引用定位播放
- **WHEN** citation 包含合法 start/end 毫秒和受控视频 URL
- **THEN** 前端 MUST 显示 `m:ss - m:ss`
- **AND** 用户操作 MUST 将播放器 seek 到 `start_ms / 1000` 附近

#### Scenario: 图片 bbox 高亮
- **WHEN** citation 同时具有受控整页预览、可换算 bbox 和完整坐标系
- **THEN** 前端 MUST 在页面图像正确位置绘制高亮
- **AND** 高亮不得遮挡主要控制或溢出页面预览

#### Scenario: 图片无整页预览或 bbox
- **WHEN** 只有图片缩略图、页码、图号或元素 ID，缺少可验证整页预览或 bbox
- **THEN** 前端 MUST 显示图片及“页内图片”或页码级信息
- **AND** MUST NOT 在缩略图上伪造页面 bbox 高亮

#### Scenario: 媒体失效和响应式布局
- **WHEN** 媒体加载、Range 或权限请求失败，或界面处于移动端宽度
- **THEN** UI MUST 保留资料名和 excerpt 并显示降级状态
- **AND** 桌面和移动端的文字、控件和媒体 MUST 不重叠
