## Why

同内容重复上传可能使 LightRAG 写入零切块的 duplicate 占位记录。现有完成校验仅按文件名选择状态，可能将该占位记录误认为当前上传，导致正文已可检索的任务在 99% 失败且不进入自动标签阶段。

## What Changes

- 将上传完成、Worker 末尾检查和标签补偿的文档选择与上传任务 provenance 绑定。
- 使其他上传留下的同名或 duplicate 零切块记录不能决定当前任务的终态。
- 在无法证明文档归属时保持可恢复的 pending/retry 状态，而非误报失败。
- 为任务归属、duplicate 占位隔离和标签入队增加回归验证。

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `upload-dedup-guard`: Duplicate-upload processing must preserve per-task document provenance through completion and automatic tagging.

## Impact

- `raganything/services/kb_service.py`
- `process_worker.py`
- `raganything/services/document_tagging.py`
- Focused upload and automatic-tagging tests
