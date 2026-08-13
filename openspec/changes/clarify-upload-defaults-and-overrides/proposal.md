## Why

知识库详情页同时展示长期上传默认和可编辑的单次分块策略，两个控件共用状态且没有明确优先级。教师无法判断哪一个会影响当前上传，批量上传还可能把前一文件解析出的默认值误写为后一文件的请求覆盖。

## What Changes

- 将知识库设置明确为长期上传默认；上传面板默认展示当前有效策略及其来源。
- 将单次分块策略改为默认收起、显式开启的临时覆盖；它仅作用于下一次提交，服务端接受请求后清除，失败时保留。
- 将 KB 默认状态和临时上传状态分离，避免保存或加载 KB 默认改变临时覆盖。
- 修正批量上传，让每个文件从同一不可变请求覆盖解析自己的快照。

## Capabilities

### New Capabilities
- `upload-default-override-clarity`: 区分知识库长期上传默认与一次性分块策略覆盖，并保持批量任务快照来源准确。

### Modified Capabilities
- None.

## Impact

- Affected frontend: knowledge-base detail upload UI and source-contract tests.
- Affected backend: batch upload snapshot loop and focused upload-setting tests.
- No public endpoint, schema, migration, historical task snapshot, or direct API compatibility change.
