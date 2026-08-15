# RAG-Anything 项目核心总结

> 本文件是所有项目任务的首要阅读入口和精简知识库。开始任务前必须完整阅读；完成任务前必须同步当前事实并追加复盘记录。它用于导航，不替代代码、迁移、运行配置或 OpenSpec。

## 0. 元信息与使用规则

| 项目 | 当前值 |
|---|---|
| 最后核验日期 | 2026-08-10（Asia/Shanghai） |
| 核验分支 | `feature/custom-enhancements` |
| 基准提交 | `52e0482714de` |
| 工作区状态 | **有未提交改动**；“进行中”内容不得视为已交付 |
| 应用版本 | FastAPI / 前端均标记为 `1.3.1` |
| 维护上限 | 目标不超过 350 行且不超过 30 KB；近期任务最多 15 条 |

### 事实优先级

发生冲突时按以下顺序判定，并在本次任务收尾时修正本文件：

1. 当前代码、数据库迁移、运行配置和已执行验证结果。
2. [`openspec/specs/`](openspec/specs/) 下的主规格。
3. [`openspec/changes/`](openspec/changes/) 下的 active change，仅表示进行中意图。
4. 已归档 change 和 [`docs/adr/`](docs/adr/) 中仍有效的决策。
5. `CHANGELOG.md`、旧功能说明书、旧架构文档等历史材料，仅作背景线索。

### 强制生命周期

- **启动**：完整阅读本文件，再根据任务范围定向核验相关源码、配置、迁移和规格；不得用本文件代替必要的局部核验。
- **执行**：发现长期有效的新事实、风险或经验时记录“总结增量”。并行子任务不得争抢本文件，只在 handoff 提交增量。
- **收尾**：唯一协调者先更新当前状态，再追加一条近期任务记录，最后检查链接、状态、日期、体积和敏感信息。
- **无持久变化**：评审、排查等任务若未改变项目事实，也必须追加一条极短记录并注明“无持久行为变化”。
- **OpenSpec**：`propose` 把总结同步列为最终任务；`apply` 在验证后更新；`archive` 前确认总结已经同步。

### 状态和安全约定

- `稳定现状`：已进入基准提交或有明确实现与验证依据。
- `进行中`：仅存在于未提交工作区或未完成 active change。
- `计划`：规格或任务已提出，但不能对外宣称已经实现。
- `已废弃`：不再作为当前模型、接口或流程使用；必要时保留兼容说明。
- 只记录环境变量名称、用途和默认行为；禁止写入实际密钥、密码、令牌、用户数据、运行日志及生成产物。

## 1. 项目定位与用户

RAG-Anything 是面向教育和专业实训场景的多模态知识库与智能体平台。它将文档解析、分块、向量与知识图谱检索、智能体问答、工作流和领域应用整合在同一 Web 产品中。

主要用户是建设内容和智能体的教师/助教、使用授权问答的学生、管理组织资源的系部管理员，以及负责全局权限、审计与部署的平台管理员。

产品与界面原则以 [`PRODUCT.md`](PRODUCT.md) 和 [`DESIGN.md`](DESIGN.md) 为专项依据；中文为主要界面语言，目标是 WCAG 2.2 AA。

## 2. 当前能力状态

### 稳定现状

| 领域 | 核心能力 | 主要入口 |
|---|---|---|
| 认证与权限 | JWT、密码、用户/角色、审计、五级 RBAC | [`routers/auth.py`](raganything/routers/auth.py)、[`services/auth.py`](raganything/services/auth.py) |
| 知识库 | 多源上传、异步任务、文档/分块/标签/图谱管理 | [`routers/knowledge.py`](raganything/routers/knowledge.py)、[`services/kb_service.py`](raganything/services/kb_service.py) |
| 多模态 RAG | 解析、分块、Embedding、实体关系、混合检索和引用 | [`raganything.py`](raganything/raganything.py)、[`query/`](raganything/query/) |
| 智能体 | 模板、CRUD、KB 绑定、会话和 SSE 问答 | [`routers/agent.py`](raganything/routers/agent.py) |
| 工作流/汽修 | 工作流运行；案例、工艺、诊断和问答 | [`routers/admin.py`](raganything/routers/admin.py)、[`routers/autorepair.py`](raganything/routers/autorepair.py) |
| 运维/前端 | 健康、指标、缓存、恢复任务；React 管理界面 | [`server.py`](server.py)、[`App.jsx`](frontend/src/App.jsx) |

- 主侧栏不再展示静态“知元服务在线”状态卡，也不显示导航分组编号、标题或分隔线；运行状态仍通过“运行监控”页面提供，避免在全局导航重复呈现未经实时校验的信息。
- 个人设置与上传面板的解析器/分块策略选项由 `GET /users/me/settings/options` 目录下发：解析器 5 种（含安装可用性、未安装置灰）、分块策略 6 种（`fixed_size`/`recursive`/`sentence`/`structure`/`semantic`/`agentic`）；平台允许列表非空时过滤、空=不限制；legacy `fixed` 渲染/保存统一归一化为 `fixed_size`；目录仅在接口失败时回退最小集合。
- 上传任务的 legacy LLM 档案按 `LLM_MODEL`、`LLM_BINDING_MODEL` 顺序解析模型；上传持久化前预检文本与 Embedding 模型。`legacy-vlm` 为兼容 ID，设置页显示实际模型 `qwen-vl-plus`；VLM OCR 兜底覆盖全部 PDF 页，上限不足显式失败。OpenDataLoader 输出根目录绝对化，结果载体携带页覆盖与来源引用，避免转换成功后路径或构造失败。
- 智能体问答的请求级设置快照必须携带 LLM/VLM 的公开 profile 指纹；知识库实例严格校验 LLM 可用性和两类指纹一致性。纯文本问答不依赖 VLM 可用性，只有图片问答和多模态处理要求可用 VLM；SSE 失败会保留错误消息，不再被会话初始化覆盖。面向用户的检索进度仅发送经过中文化的可解释阶段，第三方库的初始化、缓存、模型和存储告警只保留在服务端日志。
- 个人设置桌面工作区采用独立详情滚动：左侧分区菜单保持静止，点击项目仅滚动右侧详情；1100px 以下保留页面滚动与横向分区导航。
- 主侧栏末尾顺序固定为“用户管理、审计日志、个人设置”；权限不足时仅隐藏相应管理入口，个人设置始终位于可见列表末尾。
- 智能体启用“重排”的 RRF 查询可正常工作：失败降级为融合顺序、预算不足 1.5s 跳过；图谱检索按查询级快照执行（一次读节点/边、批量取 chunk、种子上限 20）。；检索预算默认 12s。
- 认证仅使用用户名+密码：`users.email` 列已随迁移 `025` 移除（历史数据不可恢复），注册、管理端用户管理、个人设置与审计详情均不再出现邮箱；`DEFAULT_ADMIN_EMAIL` 环境变量不再支持。

### 进行中

- **知识库成员与显示名称管理**：`manage-kb-members-and-display-name` 已在未提交工作区实现。授权行新增 `read|operate`（历史具备 `kb:write` 的成员回填为 `operate`），`kb:manage` 只授予 super_admin/dept_admin/teacher；super_admin 管理全部、dept_admin 仅自有或获授权 KB、teacher 仅自有 KB，assistant/student 不可管理成员。所有 KB 内容写入口同时要求 `operate` 范围与既有全局写权限；显示名称以 `kb_metadata.display_name` 的 `updated_at` 乐观锁更新，稳定 KB 名/工作区/索引/文档/授权关系不变。`/kb/list` 返回后端 capability，KB 页面抽屉支持改名与成员授权；管理员用户编辑中的 `allowed_kbs` 写入已拒绝。聚焦后端 42 通过、前端单测 166 通过、构建/编译/strict/diff 通过；真实 PostgreSQL 迁移及五角色浏览器验收待具备受控数据库和服务环境后执行。
- **按文件类型解析器覆盖**：`parser-per-type-overrides` + `collapse-parser-per-type-options` 已实现未提交，详见 2026-08-04 记录；per-type 解析器优先级、前端按类型三行下拉与折叠摘要已就位。
- **个人设置中心与平台设置策略**：`redesign-personal-settings-center` 规格已归档，实现仍在未提交工作区。`/preferences` 统一“个人设置”，具备独立分区保存、存储值/生效值/来源/约束展示、可执行检索预设和移动端锚点；`/admin/platform` 管理默认值、允许范围和硬上限。
- **分级个人设置权限投影**：`enforce-personal-settings-capabilities` 已实现未提交。实时权限控制分区与 API；降级的新任务继承默认，旧快照不变。
- **知识库级上传默认**：`knowledge-base-ingestion-settings` 已实现未提交。新任务按平台/个人/知识库/单次覆盖解析；KB 稀疏覆盖保存在 `kb_metadata.extra.ingestion_defaults` 并以独立 revision 乐观锁更新，不影响 `vision_embedding` 等现有元数据或历史快照。`GET/PUT /kb/{kb}/ingestion-settings` 分别要求可访问 KB 与 `kb:write`；student 无上传、配置写入或目录加载，assistant、teacher、dept_admin、super_admin 仍受既有 KB 范围约束，平台策略留在 `/admin/platform`。保留的单文件和批量文件上传入口实际使用快照的生效值。
- **视觉模型配置与混合检索链路**：工作区实现模型目录、请求/任务设置快照、作用域缓存和 KB 视觉向量重建。默认 `hybrid` 查询使用不可变的用户检索选项（含图谱深度），不修改共享检索器；KB 重建失败保留旧索引并持续显示失败状态与重试入口。生产迁移及真实 PostgreSQL 多进程验收仍取决于部署环境。
- **部署配置**：Docker 构建上下文排除 `.env`，模型目录使用只读挂载；本机没有 Docker 命令，容器构建和除 `027` 外的部署迁移未在本轮验收。
- **项目总结质量检查**：当前工作区新增标准库检查器、10 项定向测试和 non-blocking GitHub Actions workflow；本地违规仍返回非零，CI 仅用 `continue-on-error` 提示，不作为合并门禁。入口见 [`check_project_summary.py`](scripts/check_project_summary.py) 和 [`project-summary-quality.yml`](.github/workflows/project-summary-quality.yml)。
- **处理中上传任务删除**：`cancel-inflight-upload-tasks` 扩展上传抽屉和 `DELETE /upload/tasks/{task_id}`：排队任务即时删除，处理中/重试任务先进入持久化 `cancelling`，停止 worker、抑制晚到状态/重试写入并清理残留；worker 限时终止再限时强杀，未退出则保留 `cancelling` 交由轮询/恢复收敛。前端仅在服务端确认删除后移除任务。部署前须执行迁移 `024_upload_task_cancellation.sql`；真实 PostgreSQL 多进程验收仍取决于部署环境。
- **上传 claim/PG 瞬断韧性**：`harden-upload-claim-db-resilience` 已实现未提交；claim fencing、15 秒心跳、180 秒 PG 宽限和 300 秒 stale 接管已落地。真实多进程故障注入仍待部署环境验收。

- **前端导航与首屏性能优化**：`optimize-frontend-navigation-latency` 未归档，详见 2026-08-03 记录；启动链 483,290 B，较旧快照降 14.2%（非同源基线未达 ≥20%，待浏览器/nginx 验收）。
- **知识库/智能体空态布局修复**：前端页面仅在加载中或存在当前分页结果时挂载资源卡片网格；零资源、搜索无匹配和列表加载失败直接渲染主内容空态，避免桌面 `1fr` 网格将空态推到底部。未改变五级 RBAC、资源所有权或写操作门控；学生、助教、教师、系部管理员和超级管理员沿用各自可见资源与 CTA 规则。
- **图片召回与会话摘要 Schema**：`fix-agent-media-deadline-and-summary-schema` 已纳入集成检查点（未归档），实现独立媒体预算、超时保留已验证图片和幂等迁移 `027`；本地 PostgreSQL 已连续执行两次并核验摘要列与部分索引，仍待重启后的真实问答验收。
- **视频语义分段索引**：进行中；新视频固定 v2、中文分段、无页码空块；legacy 处理器/整段模板退役，遗留未完成任务取消或以 `video_profile_retired` 失败，历史成品不回填。段字数回写且重试不累计；帧短暂不可读重试，持续失败以可重试 `video_frame_encode_failed` 输出，不走 Docling/OCR 兜底或误报完成。批量以完整任务 ID 隔离暂存，逐文件稳定序号并区分重复跳过/注册失败、清理未入队文件。聚焦 151 通过、2 跳过；真实 Worker/PG 待验收。v2 索引吞吐优化已落地（`optimize-video-index-throughput`）：新增阶段耗时指标（`video_v2_metrics`/`video_v2_segment_metrics`）、`VIDEO_SEGMENT_CONCURRENT`（默认 2、上限 4）受控并发处理独立片段、按片段序号确定性写入、v2 延迟整文档落盘消除逐块 JSON 全量重写。

### 计划与待收敛 OpenSpec

截至 2026-07-30，active change 的勾选数只用于导航，不代表发布状态：

| Change | 已完成/待办 | 当前判断 |
|---|---:|---|
| [`canvas-rendering-migration`](openspec/changes/2026-07-02-canvas-rendering-migration/) | 0/24 | 计划，待确认 |
| [`orderly-graph-layout`](openspec/changes/2026-07-02-orderly-graph-layout/) | 39/8 | 进行中 |
| [`manufacturing-to-autorepair`](openspec/changes/2026-07-03-manufacturing-to-autorepair/) | 0/26 | 清单落后，待复核/归档 |
| [`add-opendataloader-pdf-parser`](openspec/changes/add-opendataloader-pdf-parser/) | 23/38 | 部分落地，待复核 |

### 已废弃或不得当作当前事实

- 三角色 `admin/editor/viewer` 仅作迁移映射；当前为五级角色。
- `auth.db`/SQLite 不再是认证权威存储；当前要求 PostgreSQL。
- `users.email` 字段与 `DEFAULT_ADMIN_EMAIL` 环境变量：2026-08-03 全链路移除（迁移 `025` 删除列），历史邮箱数据不可恢复；历史说明书仍含旧示例，仅作背景材料。
- 旧 `/upload`、`/query`、单一 `SettingsPage` 和 `manufacturing:*` 描述已过时，以当前路由和 `autorepair:*` 为准。

## 3. 架构与关键数据流

### 分层

`React/Vite 前端 -> FastAPI Router -> Service -> RAG/Core -> PostgreSQL、向量/图存储、Redis、文件工作区`

代码依赖必须保持 `Router -> Service -> Core -> Infrastructure`。`raganything/` 包不得反向依赖根目录脚本。

### 关键数据流

- **文档处理**：上传 API 创建任务 -> Worker 解析文本/多模态内容 -> 分块、标签、Embedding、实体关系与索引 -> PostgreSQL/KB 工作区持久化 -> 轮询、SSE 或 WebSocket 反馈；失败任务进入重试或修复。
- **查询与智能体**：JWT/RBAC/KB 范围校验 -> 智能体选择知识库、提示词和上下文 -> 关键词、向量、图谱、标签、图像联合召回 -> LLM 生成带来源答案 -> 会话与历史写入 PostgreSQL。

### 数据边界

- PostgreSQL 是认证、共享状态和业务仓库的必需后端；迁移见 [`migrations/`](migrations/)。
- **架构取证（2026-08-05）**：后端为模块化单体 + 子进程 Worker；缓存/WS 在进程内。Redis 仅见 Compose；`/ws` 未按用户/KB 过滤。
- `WORKING_DIR`、上传、输出和 ODL 产物按任务/实例隔离；Redis 与外部图/向量存储由环境配置。
- 浏览器只访问受控 API/媒体入口，不能接收本地路径、模型目录或密钥。

## 4. 核心目录导航

| 路径 | 职责 |
|---|---|
| [`server.py`](server.py) | FastAPI 组装、路由挂载、启动/关闭、监控和进程锁 |
| [`raganything/`](raganything/) | RAG 核心及解析、分块、Embedding、图谱、查询模块 |
| [`raganything/routers/`](raganything/routers/) / [`services/`](raganything/services/) | HTTP/WebSocket 边界与业务/仓库层 |
| [`process_worker.py`](process_worker.py) | 隔离的文档处理 Worker 入口 |
| [`frontend/src/`](frontend/src/) | React 页面、组件、状态和 API 封装 |
| [`migrations/`](migrations/) / [`tests/`](tests/) | PostgreSQL 演进与后端/安全/回归验证 |
| [`openspec/specs/`](openspec/specs/) / [`changes/`](openspec/changes/) | 主规格与进行中变更 |
| [`docs/`](docs/) / [`scripts/`](scripts/) | 专项资料与有副作用的辅助入口；使用前核验 |

## 5. 核心业务规则

### RBAC v2

权限常量以 [`raganything/permissions.py`](raganything/permissions.py) 为准，格式为 `resource:action`。默认角色为 `student`。

| 角色 | 业务定位 |
|---|---|
| `super_admin` | 全部权限；`is_admin` 仅作为由该角色派生的兼容字段 |
| `dept_admin` | 组织用户、知识库、智能体及业务管理 |
| `teacher` | 自有 KB/智能体读写及教学业务能力 |
| `assistant` | KB 内容维护、智能体使用和受限业务能力 |
| `student` | 获授权的读取与问答能力 |

关键不变量：

- 受保护接口使用 [`require_permission()`](raganything/dependencies.py)，不得以 `is_admin` 建立新授权模型。
- `is_admin` 仅由 `super_admin` 派生；前端展示权限不能替代服务端校验。
- 用户、角色、审计、JWT 撤销和登录保护由 PostgreSQL auth service 管理。
- 旧三角色用户通过 [`015_restore_5level_rbac.sql`](migrations/015_restore_5level_rbac.sql) 映射到五级角色。
- 角色分配等级约束：`can_assign_role()`（`ROLE_ORDER/ROLE_RANK`）限定操作者只能分配不高于自身等级的角色；`create_user/update_user` 强制校验，bootstrap 以 super_admin 豁免。
- 会话属“使用”资源：创建/重命名/删除按 `agent:read`（保留所有权校验），消息编辑按 `agent:write`。
- `GET /kb/{kb}/vision-settings` 按 `kb:read`+可见性读取，写入保持属主/`kb:write`；`GET /workflows/models` 需 `workflow:read`。
- 运行时角色种子由 `DEFAULT_ROLES` 派生（`build_default_role_rows`），PG 模式删除 KB 已修复。

### 知识库与任务

- 非管理员只访问授权 KB；工作区、缓存、历史和媒体必须隔离。
- 上传状态需可恢复/重试并避免重复入库；删除同步清理状态、索引、媒体和缓存。
- 图谱、分块、标签编辑保持 KB 范围和缓存/索引一致性。

### 设置、智能体与媒体

- 平台设置与个人设置是不同权限域；个人设置中心实现尚未提交时，以已提交接口为稳定基线。
- 智能体必须绑定调用者可访问的知识库；会话和消息按用户/智能体隔离。
- 媒体路径不得直接暴露本地文件系统；使用受控媒体端点和授权信息。

## 6. 技术栈、配置与运行

### 技术栈

- **后端**：Python `>=3.10`、FastAPI/Uvicorn、RAG-Anything/LightRAG、asyncpg、Prometheus。
- **解析/检索**：Docling、MinerU、PyPDF、可选 OpenDataLoader/PaddleOCR、向量/关键词/图谱检索；Docling 为必装依赖。
- **前端**：React 18、Vite 5、Router、D3/XYFlow/Recharts、Tailwind CSS。
- **基础设施**：PostgreSQL 16、Redis 7、Compose/Nginx，可选外部图/向量库。

### 配置类别

以代码中的 `os.getenv()` 和部署配置为准。[`.env.example`](.env.example) 含大量注释示例但仅启用基础项，[`env.example`](env.example) 覆盖更完整；两者范围不同且可能含历史描述，均不能单独作为事实源。

- 模型：`LLM_BINDING*`、`LLM_MODEL`、`VISION_MODEL`、`EMBEDDING_*`。
- 数据与工作区：`DATABASE_URL`、`POSTGRES_*`、`REDIS_URI`、`WORKING_DIR`、可选图/向量存储变量。
- 处理：`MAX_ASYNC`、`MULTIMODAL_*`、`PROCESS_*`、`AUTO_TAG_*`、切块/解析/缓存/模型预检变量。
- 安全与运维：`JWT_*`、`DEFAULT_ADMIN_*`、登录锁定、`LOG_*`、`ENABLE_METRICS`、`METRICS_PATH`。

敏感变量在生产必须显式设置且不得提交。`config/runtime_settings.json` 是运行时覆盖入口；模型目录以部署配置和 [`config/vision_models.json`](config/vision_models.json) 等受控文件为准。

### 常用命令

```powershell
# 本地后端：server.py 默认端口为 8001，可由 PORT 覆盖

# 前端

# 后端测试

# 项目总结质量；本地严格返回检查结果，CI 仅作非阻断提示

```

数据库初始化入口为 [`scripts/pg_setup.py`](scripts/pg_setup.py)，会创建数据库、执行迁移并修改 `.env`，运行前必须检查迁移清单和凭证处理。容器链当前存在已知问题，修复并验证前不要把 `docker compose up --build` 视为可用发布命令。

## 7. 开发约束与最低验证

- 每次请求执行两级调度；OpenSpec 额外遵守 [`AGENTS.md`](AGENTS.md) 的专家数量和时序。
- 并行规则见 [`parallel_collaboration_rules.md`](docs/parallel_collaboration_rules.md)；迁移、权限、锁文件、入口和本文件串行维护。
- 保留用户既有改动，不重置、覆盖或格式化无关文件。
- 后端跑相关 `pytest`；共享边界扩大回归。前端跑 `test:unit`，页面/样式再跑 build 和视口检查。
- 迁移验证顺序、幂等、升级与兼容；文档验证链接、结构、敏感信息和 `git diff --check`。

## 8. 已知风险与常见问题

- 2026-06 文档和 [`docs/architecture.md`](docs/architecture.md) 已落后，引用前需核验。
- `pyproject.toml` 声明 `README.md`，但仓库根目录当前缺少该文件；这是独立遗留问题。
- 两份 env 示例覆盖不一；`pg_auth_repo.py` 说明仍残留旧角色/回退描述。
- 已跟踪的 `tests/test_auth.py` 仍有 3 条断言期待 `viewer/admin`，与当前 `student/super_admin` 角色结果冲突，需定向更新而非删除整份有效测试。
- OpenSpec 勾选与代码、迁移编号与演进修正均有漂移，不能按表面状态判断。
- 容器链尚未验收：Dockerfile 在未安装 Node/npm 的 Python 基础镜像中构建前端，Compose 仍挂载旧 `auth.db`，容器端口/健康检查和 `frontend_dist` 产物链也需统一。
- 当前工作区含多组未提交修改；并行实例共享目录、数据库或端口会污染状态。
- 持久上传重试依赖后端进程内调度器；任务在后端停止时不会丢失，但会暂停到进程恢复。生产部署须启用 [`deploy/rag-anything.service`](deploy/rag-anything.service) 或等效服务管理器的自动拉起，不能只依赖交互式终端进程。
- 未提交的请求级设置实现会为每次智能体问答创建未缓存的 KB 实例并让默认 `hybrid` 改走三通道 RRF；性能验收前须补齐分阶段观测并恢复可复用的配置隔离实例。

## 9. 总结更新矩阵

| 任务类型 | 必须更新的当前事实 | 近期记录重点 |
|---|---|---|
| 新增 | 能力、入口、模块、数据流、配置、权限、迁移 | 结果、影响范围、验证 |
| 优化 | 直接替换旧行为和指标，不并列保留矛盾描述 | 前后差异与收益 |
| Bug 修复 | 症状、根因、修改边界、预防规则 | 复现与回归验证 |
| 配置/业务/技术变更 | 默认行为、优先级、兼容、部署和迁移要求 | 决策依据与风险 |
| 删除/废弃 | 从稳定现状移除，转入废弃说明 | 原因、遗留适配、清理项 |
| 经验/排查 | 只保留可复用检测、规避和标准流程 | 结论；无持久变化也记录 |

近期任务固定字段为“日期、任务/change、类型、结果、影响范围、验证、经验/风险”。超过 15 条时，将最旧记录按月份和子系统归并为里程碑；每月每子系统最多一条，详细历史继续由 Git/OpenSpec 承载。

## 10. 近期任务记录

| 日期 | 任务/change | 类型 | 结果 | 影响范围 | 验证 | 经验/风险 |
|---|---|---|---|---|---|---|
| 2026-08-10 | 项目开发看板更新 | 项目管理/无应用行为变更 | 看板改为当前交付的五模块、六阶段；14 项本地已实现任务默认勾选为“实现完成”，外部验收保留在备注。 | `项目管理看板.html`、项目总结 | 任务/依赖/状态/默认勾选、内嵌 JS 语法、版本化存储迁移校验；看板定向 diff check 通过 | “实现完成”不代表 PG/Worker/浏览器/云端或生产验收；旧浏览器 key/hash 保留但不加载。 |
| 2026-08-07 | `manage-kb-members-and-display-name` | 功能/OpenSpec、进行中 | KB 成员授权由旧用户编辑器迁移至 KB 级 API/抽屉；grant 区分只读/可操作，改名仅写显示名称并由元数据版本拒绝并发覆盖；五级角色按 scope + 全局能力双重校验。 | 迁移 033/034、RBAC/认证仓库、KB 路由与写入口、KnowledgePage/API、用户编辑器、聚焦测试 | 后端 42、前端 166、Vite build、py_compile、OpenSpec strict、作用域 diff 通过；迁移 runner 本机无 PostgreSQL 凭据无法读取状态 | 未执行真实 PG fresh/upgrade/repeat/failure、旧会话撤权 HTTP 与五角色浏览器/375px 实测；部署前需已验证备份后执行受控迁移。 |
| 2026-08-06 | `optimize-video-index-throughput` | 性能/OpenSpec、进行中 | v2 视频分段阶段耗时指标（探测/抽帧/ASR/场景/VLM/抽取/PG/总耗时，含失败 `failed=true`）；`VIDEO_SEGMENT_CONCURRENT`（默认 2、上限 4）受控并发处理独立片段；并发结果按 `segment.index` 归位，PG/`chunk_ids`/`chunk_results` 确定性顺序；`_create_entity_and_chunk` 新增 `defer_flush`/`defer_extraction`（默认行为不变），v2 延迟到整文档 `_insert_done()` 落盘。 | 视频处理器、modalprocessors/base、config、env.example、相关 tests | 聚焦 104 通过、2 跳过；`py_compile`、OpenSpec strict、`git diff --check` 通过 | 评审/测试子代理曾因项目铁律递归派生子代理失控，已中断并由协调者自审补位；`test_callbacks.py::test_process_document_emits_callbacks` 为既有 doc_processor PDF 路径失败，与本次无关；真实 Worker/PG 时长收益与检索验收待部署验证。 |
| 2026-08-06 | 上传/分页 | UI | 上传折叠；10条/页、分页居中。 | 详情 | 单测/构建 | UI |
| 2026-08-06 | v2 视频帧/批量反馈 | Bug/OpenSpec、进行中 | 帧短暂不可读重试；持续失败为可重试 `video_frame_encode_failed`，Worker 不再经 Docling/OCR 兜底或误报完成；批量注册失败返回逐文件错误；已启用只读上传监控。 | 视频、Worker、上传 | 聚焦 151 通过、2 跳过；编译、strict、总结、diff 通过 | 重启后生效；未改写历史任务，真实 Worker/PG 新上传待验收。 |
| 2026-08-05 | `fix-kb-card-update-time` | Bug/OpenSpec、进行中 | 列表新增 `last_updated_at`，兼容旧字段；卡片/排序优先新字段。`031` 移除遗留触发器，并对重复时间按终态上传/语料提交最佳可得回填。 | KB 列表、卡片、迁移 | 后端 17 通过、PG 1 跳过；前端 155/155、构建、OpenSpec strict 通过 | 现网须在备份和预览后确认 `026`/`031`；历史设置时间无法精确恢复。 |
| 2026-08-05 | Docling ASCII 镜像自愈修复 | Bug 修复 | 残缺镜像 + os.replace 无法覆盖已存在非空目录导致启动失败；锁内先移除残缺镜像再原子替换 | office_parser.py | 定向重建镜像、py_compile、diff check 通过；tiktoken 下载受沙箱网络阻塞未全量启动 | 无 API/迁移变更 |
| 2026-08-05 | `architecture-overview-deep-dive` | 架构文档 | 确认单体 + Worker、PG/LightRAG/工作区与 32 项迁移。 | 全栈/Compose | 源码核验、两级审查、15 页渲染 | Redis 未证实接入；`/ws` 未按用户/KB 过滤；未跑容器/PG/SSE。 |
| 2026-08-05 | `video-semantic-segment-index` | 功能/OpenSpec、进行中 | v2 新上传支持确定性视频分段、时间引用、受控播放和失败补偿清理；已覆盖迁移、认证、CRUD、入口分发与隔离 PG 验收 | 视频处理/分段服务、KB 入口、迁移 029/030、相关 tests | 视频聚焦 105 通过 2 跳过；PG 集成、OpenSpec strict、py_compile、diff check 通过 | Recall@5/MRR 与真实 Worker 样片 E2E 待 5.3；Docker 暂缓 |
| 2026-08-05 | 视频分段中文化/批量字数 | Bug 修复 | 新段中文化、纯视频无页码空块；字数重试不累计，批量任务隔离并按 `file_index` 回填。 | 视频、上传 | v2 聚焦 162 通过、2 跳过；前端 157/157 | 真实 Worker/PG 待验收；历史 legacy 不改。 |
| 2026-08-05 | `knowledge-base-ingestion-settings` | 功能/OpenSpec、进行中 | 个人 -> KB -> 单次三层 ingestion 默认，KB 稀疏值/revision 存 `kb_metadata.extra`，五个上传入口使用不可变快照；学生无写入目录/控件。 | settings、KB API/页面、测试 | 后端 100、前端 25、语法、OpenSpec、diff、构建通过 | 未做真实 PG 多角色和浏览器上传验收。 |
| 2026-08-04 | `parser-per-type-overrides` | 功能/OpenSpec | 个人设置支持按 pdf/office/image 覆盖解析器，运行时按 per-type > 全局优先级；前端目录下发可用性与类型约束 | user settings、parser dispatch、KB upload、Preferences | 后端 75、前端 20 通过；py_compile/OpenSpec validate 通过 | Vite build 和重启后实测待环境；与 parser options delta 需合并 |
| 2026-08-04 | `collapse-parser-per-type-options` | 功能/OpenSpec | 个人设置上传/解析区渐进式折叠：全局下拉改名「默认解析器」并加说明，PDF/办公/图片三行收进 `<details>`「按文件类型指定（可选）」，折叠摘要由新工具 `summarizeParsersByType` 生成（pdf→office→image 规范顺序、忽略空值/未知键、drafts ?? effective 实时反映）；主网格拆两段、折叠区居中；summary 样式并入既有规则（含 dark）；纯前端，后端/接口/数据不变 | `PreferencesPage.jsx`、`index.css`、`parserTypeOptions.js`(+test)、change 工件 | parserTypeOptions 单测 15/15、前端工具全量 152/152（frontend 目录）、JSX/JS 语法解析通过；两级调度（2 提案评审+1 执行+1 审查+1 测试）通过 | Vite build 仍受沙箱 esbuild 目录读取权限 + 自动审批服务故障阻塞，需用户侧运行；与 parser-per-type-overrides 等 3 个 change 的 personal-settings-center delta 同区，归档时合并清理 |
| 2026-08-04 | `restore-chunking-parser-options` | Bug 修复/OpenSpec | 设置整合（1857767）回归修复：个人设置分块策略下拉由硬编码 2 项改为 options 目录 6 项；解析器下拉由空（allowed 空数组被当无选项）改为目录渲染、未安装置灰；上传面板切块选择器恢复加载（`strategies` 不再为空）；`fixed`→`fixed_size` 三处归一化；mineru 安装检查加 10s 超时 | `raganything/services/user_settings.py`、`routers/user_settings.py`、`parser/pdf_parser.py`、`PreferencesPage.jsx`、`KnowledgeDetailPage.jsx`、`chunkingOptions.js`、相关 tests | 后端 29+99、前端 137 通过；py_compile、OpenSpec strict、diff check 通过；两级调度（2 提案评审+1 审查+1 测试）通过；Vite build 受沙箱 esbuild 权限阻塞 | 空数组目录=平台限制应渲染为空、仅接口失败才回退；无 ingestion 用户不构建/返回目录；解析器探测 TTL 60s 且异常记为不可用 |
| 2026-08-03 | `optimize-frontend-navigation-latency` | 前端性能优化、进行中 | 导航与按需加载优化 | frontend | 单测、构建、strict 通过；启动链降 14.2% | 非同源基线；浏览器/nginx 待验收 |
| 2026-08-05 | `harden-upload-claim-db-resilience` | Bug 修复/OpenSpec、进行中 | 区分 PG 瞬断与 claim fencing；修正 asyncpg 0.31 连接池参数；上传/KB mutation 租约窗口、一次性终止与 durable 恢复；四类后台循环指数退避和恢复日志；补充 provenance/owner-generation 回归 | `pg_state_repo.py`、`kb_service.py`、`kb_mutation.py`、`upload_retry.py`、`document_tagging.py`、相关 tests/OpenSpec | 五文件套件 140 通过；无未等待协程；py_compile/OpenSpec strict/diff check；本机 PG 两端点 200 | 未执行真实 PostgreSQL 故障注入、跨进程 owner 争抢及数据重复核验；工作区仍含并行无关未提交改动 |


## 11. 历史里程碑

- **2026-07-31 `restore-agent-query-latency`（性能修复）**：共用 deadline 与租约感知 SSE 清理；RRF 尾延迟 71s 已改 context-only 返回。
- **2026-08-01 `consolidate-frontend-streaming-client`（冗余治理）**：SSE 统一共享认证传输；删除含硬编码凭据的测试文件。
- **2026-08-03 智能体检索冷/热请求复核（性能排查）**：冷请求初始化+改写耗尽 8s；graph 通道占满预算。
- **2026-07-31 upload robustness & recovery**：迁移 `023/024` 补齐租约与可取消队列；worker 按显式任务元数据预检、模型回退、PDF OCR 兜底与完成回写；Embedding 瞬时失败按持久作业重试、环境恢复后自动完成；ODL 输出根目录绝对化并携带 `provenance_ref`。39 页受控重试通过、37/37 文本向量、标签 36/36；生产启用前执行 `023/024`。
- **2026-07**：完成智能体会话上下文升级、视频/多模态处理、文档质量/标签/修复/上传重试、评估流水线和 OpenDataLoader 集成；个人设置与视觉能力继续迭代。
- **详细历史**：优先查看 Git 提交与 [`openspec/changes/archive/`](openspec/changes/archive/)；[`CHANGELOG.md`](CHANGELOG.md) 仅覆盖较早阶段。

## 12. 详细资料索引

- 产品定位与体验：[`PRODUCT.md`](PRODUCT.md)、[`DESIGN.md`](DESIGN.md)
- 主规格：[`openspec/specs/`](openspec/specs/)
- 进行中变更：[`openspec/changes/`](openspec/changes/)
- 架构决策：[`docs/adr/`](docs/adr/)
- 并行协作：[`docs/parallel_collaboration_rules.md`](docs/parallel_collaboration_rules.md)
- OpenDataLoader：[`docs/opendataloader_pdf.md`](docs/opendataloader_pdf.md)、[`docs/opendataloader_supply_chain.md`](docs/opendataloader_supply_chain.md)
- 知识库测试：[`docs/knowledge-base-test-plan.md`](docs/knowledge-base-test-plan.md)

## 13. 2026-08-06 HNSW ingestion memory hardening

- HNSW OOM (`53200`/context) is terminal `graph_index`: no degraded or auto
  retry; lease-fenced retry-now only. Compose profile, health check, and
  runbook added. Focused 98 tests, py_compile, strict, and diff passed; full
  pytest is blocked by unrelated PG-pool setup. Compose/live PG/MP4 E2E pending.

## 14. 2026-08-06 LightRAG embedding identity and KB isolation

- Added `stabilize-lightrag-embedding-kb-isolation`: upload snapshots now freeze
  a secret-free provider/model/endpoint/dimension identity; LightRAG table
  namespaces, semantic chunking, cache, Worker and query compatibility use the
  same identity. Unsafe `PG_WORKSPACE` overrides fail before initialization.
- Added additive migration `032_kb_text_embedding_identity.sql`, locked KB
  identity registration, legacy unsuffixed-vector blocking, and an admin-only
  read-only diagnostic endpoint. Existing vectors are not copied or rewritten.
- Focused identity/settings/Worker/KB tests: 51 passed; `py_compile` and
  `git diff --check` passed. OpenSpec strict validation passes for this change;
  repository-wide validation still reports three unrelated pre-existing changes.
- Real PostgreSQL Worker upload acceptance passed 2026-08-06: fresh scratch KB
  upload runs the worker to `completed` (entity-extraction -> graph-building),
  registers the workspace identity with the environment hash, writes
  chunks/entities/relations into the identity-suffixed vector tables only
  (`lightrag_vdb_chunks_openai_compa_639985a6e4b87473_1024d` etc.), and the
  automatic tagging content-readiness gate passes. `evaluate_content_readiness`
  and `cleanup_failed_invalid_residue` now resolve the physical vector chunk
  table via `resolve_vector_chunk_table` (case-insensitive `pg_class` lookup
  returning the real lowercase relname, identity-suffixed preferred, legacy
  fallback) instead of the hard-coded unsuffixed `LIGHTRAG_VDB_CHUNKS`;
  focused tests 116 passed, `py_compile`/`git diff --check` clean. Full pytest
  still blocked by unrelated PG-pool setup tests.
- 2026-08-06 崩溃修复与本地验收（并入本 change）：`_legacy_rows` 改为
  information_schema 大小写不敏感存在性 + workspace 列检查，缺表/缺列返回 0
  不中止事务（原带引号大写查询无法发现小写 legacy 表，缺表时吞错后事务被
  PostgreSQL 标记 aborted，导致 `InFailedSQLTransactionError` 启动崩溃）；
  诊断端点同步 ILIKE 发现 + 小写 legacy 比较。迁移 `031/032` 已应用本地 PG
  （应用前已备份）。live 验收通过：`python server.py` 启动成功、
  `./rag_storage` 身份注册落库、suffixed 向量表创建、legacy workspace
  （`./rag_storage_新能源`）被 `embedding_legacy_storage_incompatible` 阻止
  且无注册写入、诊断正确标记 legacy 表；focused 26 测试通过。

## 15. 2026-08-06 排查与修复：embedding identity 启动崩溃

- 现象：`python server.py` 启动即 `Application startup failed. Exiting.`，报错为 `pg_embedding_identity.py:26` 的 `InFailedSQLTransactionError`。
- 根因（已实测复现）：`ensure_kb_embedding_identity` 在事务内用带引号大写 `"LIGHTRAG_VDB_*"` 做 legacy 计数；LightRAG 实际以小写未引号建表，该查询必然 `UndefinedTableError`，被 `_legacy_rows` 吞掉但 PostgreSQL 已把整个事务标记为 aborted，第二条 COUNT 即抛 `InFailedSQLTransactionError` 上抛。
- 附带：迁移 `032`（`kb_text_embedding_identities`）当时未应用；当前 PGVectorStorage 使用带 identity 后缀的 suffixed 表，unsuffixed 表仅承载 legacy 数据，修复后 legacy 探测不误伤当前存储。
- 处置：按 OpenSpec 并入 `stabilize-lightrag-embedding-kb-isolation`（任务 2.4/3.1/3.3/4.4）修复并完成本地 PG 验收，详见第 14 节。
- 2026-08-06 Worker 上传验收阻塞与修复：首次 live 启动 `embedding_identity_conflict`
  源于 asyncpg 将 JSONB 返回为字符串，`ensure_kb_embedding_identity` 已按 str
  解析（回归测试 2 条）；Worker 曾连续 Rust OOM，根因是残留 `server.py` 子进程
  堆积（venv python 是 launcher，`terminate()` 只杀 launcher），验收脚本改为
  `taskkill /PID /T /F` + 启动前释放端口；最后阻塞为内容就绪检查直查未后缀
  `LIGHTRAG_VDB_CHUNKS` 导致 `vector_count=0`，已由任务 2.5 的 suffixed 表解析
  修复；真实 Worker 上传验收最终 `completed`（chunk=1/entity=16/relation=21，
  suffixed 表落库、标签门禁通过），scratch 数据已清理。

## 16. 2026-08-06 火山引擎云服务器部署指南

- 新增 [deploy/volcano-engine-docker.md](deploy/volcano-engine-docker.md)：Docker Compose 部署到火山引擎 ECS 的完整手册（SSH、Docker 安装与国内镜像、代码上机、.env 必填项、构建/启动、安全组、HTTPS、备份与升级、FAQ）。
- 部署要点：RAGANYTHING_ENV=production 时强制要求 JWT_SECRET/JWT_REFRESH_SECRET/DEFAULT_ADMIN_PASSWORD/DATABASE_URL 及视觉目录 pi_key_env；compose 内 DATABASE_URL host 必须为 postgres；MIGRATION_BACKUP_ACKNOWLEDGED=true 为迁移闸门。
- 本次仅新增文档，未改动运行代码、配置或迁移；应用行为无持久变化。

## 16. 2026-08-06 purge legacy embedding vectors（存量 KB 查询恢复）

- Applied `purge-legacy-embedding-vectors`：propose 阶段 2 位专家评审、apply 阶段 3 位专家（执行/审查/测试）全部通过；脚本、测试与 OpenSpec 变更已落地。
- 新增一次性运维脚本 `scripts/purge_legacy_embedding_vectors.py`：`--dry-run` 大小写不敏感发现 legacy 与全部 suffixed 向量表（information_schema + workspace 列），输出行数基线与孤儿行清单；`--apply` 必须通过 `--backup-dir` 门禁（dump 非空且精确匹配 `COPY public.<表>`），单事务内取 workspace 级 advisory lock，以 `./rag_storage` 为权威身份并逐字段交叉校验运行时 env，逐 workspace `FOR UPDATE` 冲突校验（INSERTED/EXISTED），DELETE 后逐表校验 0 行；suffixed 孤儿行需 `--force`；幂等；退出码 0/2/1；错误输出 DSN 脱敏。
- 本地 PG 16 已执行：三张 legacy 表与身份表备份到仓库外目录（行数 4047/19124/48290 与基线一致），`--apply` 将 7 个 workspace 全部注册（hash 639985a6…）并删除 71461 行，逐表校验 0 残留。
- 回归：`create_rag` + `_ensure_lightrag_initialized` 对 视频/odl解析 均 `{'success': True}`（此前 28ms 内 `embedding_legacy_storage_incompatible` 拦截）；server 启动探针 `/api/live` 返回 `{"status":"live"}`，启动日志 0 次 `embedding_legacy_storage_incompatible`、0 次 `PG doc_status instance unavailable`。
- 端到端验收（2026-08-06 用户本机完成）：重建视频 KB 并上传 `1、规范停放车辆.mp4`（13.8MB），任务 `completed`；产出 2 个中文分段（`video_segments` 含中文 `transcript_text`/`visual_summary`），向量写入新后缀表 `..._openai_compa_639985a6e4b87473_1024d`（chunks=2 / entity=31 / relation=64），`doc_status=processed`；智能体查询返回带引用答案并落库（1 会话 2 消息），全程无 `embedding_legacy_storage_incompatible`。空 legacy 表保留且无害（守卫按行数判定 0）。
- 环境经验（本机 Windows）：视频处理硬依赖系统 PATH 中的 ffmpeg/ffprobe（`raganything/video_processor/__init__.py` 裸调、无 `FFPROBE_PATH` 配置入口、无启动预检），缺失时上传报 `video_ffprobe_unavailable`（可重试但环境缺失无法自愈）；修复为 `winget install --id Gyan.FFmpeg -e` 后必须从新终端重启 server/worker 使 PATH 生效。另：Embedding（DashScope）`model_preflight` 20s 超时曾因网络瞬断出现，网络恢复后重试即过，非代码问题。
- 检查：29 项脚本自检 + 60 项相关 focused 测试（identity/upload-retry/kb-mutation/migration）、`py_compile`、OpenSpec strict、`git diff --check` 全部通过。
## 17. 2026-08-06 前端遮罩去蓝化（neutralize-overlay-backdrops）

- 全站弹窗/抽屉遮罩蓝色调改为等透明度中性黑：JSX 遮罩 `bg-sky-900/20|25` -> `bg-black/20|25`（KnowledgePage 删除/新建知识库、AgentsPage 删除智能体、WorkflowPage 确认/加载、KnowledgeDetailPage 图谱三弹窗，共 8 处）；index.css 中 `.agent-config-overlay`/`.side-drawer-layer`/`.user-dialog-layer`/`.user-dialog-layer--confirmation` 的 navy rgba 背景及 `.agent-config-overlay::after` 浅色渐变改为 `rgba(0,0,0,...)`。
- 保留模糊：集中式 blur 规则选择器同步换为 `bg-black/*` 变体，`blur(8px)` 不变；agent-config 自身规则 blur 不变；侧边抽屉/用户弹窗原本无模糊，未新增。
- 验证：OpenSpec propose 2 专家评审、apply 3 专家（执行/审查/测试）全部通过；前端单测 157/157、`npm run build` 通过、dist 产物与 src 残留搜索干净、`git diff --check` 通过。纯前端视觉改动，无 API/后端/数据库变更。
## 17. 2026-08-06 火山引擎 ECS 部署任务（运维，无代码改动）

- 目标：部署到 115.190.170.186（root）。沙箱外联 SSH 的自动审批服务持续返回评审模型配置错误，无法从本环境直连；改为交付离线部署包由用户在服务器执行。
- 产物（均不在仓库内）：C:\Users\98014\.codex\visualizations\2026\08\06\019fd5fb-16da-72a3-8ed4-de1569dbe3b7\volcano_deploy\bundle\（源码包 ag-anything-src.tar.gz、deploy_server.sh 一键脚本、env.custom 由本机 .env 导出、README）。
- 部署要点：RAGANYTHING_ENV=production；DATABASE_URL host 用 compose 服务名 postgres；MIGRATION_BACKUP_ACKNOWLEDGED=true 迁移闸门；生产校验要求 JWT/管理密码/DATABASE_URL 与视觉目录 pi_key_env。手册见 deploy/volcano-engine-docker.md。
- 本次仅运维准备，未改动运行代码/配置/迁移；应用行为无持久变化。
## 18. 2026-08-06 部署修复：补充缺失运行依赖 slowapi

- 现象：服务器镜像构建/迁移成功，但 aganything-app 崩溃循环 ModuleNotFoundError: No module named 'slowapi'（server.py:30 使用 slowapi 限流）。
- 根因：slowapi 是运行时依赖，但 equirements.txt 与 pyproject.toml 均未声明（本地 venv 为手工安装）。
- 处置：equirements.txt 与 pyproject.toml [project].dependencies 均补充 slowapi>=0.1.9,<0.2；服务器侧用 docker commit 在现有镜像内补装（避免 40 分钟全量重装），后续重建镜像将自带该依赖。
## 19. 2026-08-06 部署修复：requirements 缺失运行时依赖（slowapi/jwt 等）

- 现象：镜像构建与迁移成功，但 app 逐模块 ModuleNotFoundError（先是 slowapi，后是 jwt/passlib 等）。
- 根因：equirements.txt/pyproject.toml 仅声明少量包，运行时（server.py + raganything/）还依赖 PyJWT、passlib、python-docx、pypdfium2、aiohttp、Markdown、psutil、reportlab、beautifulsoup4 等，本地 venv 系历史手工安装。
- 处置：补齐 equirements.txt 与 pyproject.toml dependencies；服务器侧一次性补装缺失包并 docker commit 镜像（docker-compose.override.yml 固定 entrypoint 规避镜像 CMD 污染）。
- 说明：weasyprint/paddleocr/whisper/marker/opendataloader 均为惰性或受保护导入，未列入必装；后续重新构建镜像将自带全部依赖。
## 20. 2026-08-06 部署完成：火山引擎 ECS 已上线（115.190.170.186）

- 状态：docker compose 全栈运行，/api/health 200，Application startup complete；migrate 应用 35 个迁移，默认管理员已创建（凭据在服务器 /root/rag-anything-credentials.txt）。
- 关键处置：镜像缺依赖逐项补装并 commit（slowapi/PyJWT/passlib/python-docx/pypdfium2/aiohttp/Markdown/psutil/reportlab/beautifulsoup4），docker-compose.override.yml 固定 entrypoint: ["python","server.py"]；管理员密码改为符合策略的随机串。
- 已知降级：postgres 为基础 postgres:16-alpine（无 pgvector/AGE），向量存储 NanoVectorDB、图谱 NetworkX；如需 HNSW/AGE 需换带扩展的镜像并重建。
- 交付物：deploy/volcano-engine-docker.md 部署手册；部署包位于可视化目录 olcano_deploy/bundle/（含 env.custom 真实密钥，建议部署完成后删除本地副本）。
## 21. 2026-08-06 管理员密码重置（运维）

- 按用户要求重置服务器管理员密码：登录接口疑似命中锁定/限流，改用应用自身 passlib/bcrypt 直接更新 users 表（同时清除 ailed_login_attempts/locked_until、must_change_password=0）。
- 验证：POST /api/auth/login 返回 ccess_token，角色 super_admin。.env 与 /root/rag-anything-credentials.txt 已同步。
- 无代码改动；密码值不记录于本文件。

## 22. 2026-08-07 云服务器开发与环境差异排查（运维，无代码改动）

- 解析器便携化实现进行中：默认 Docker 镜像声明 PaddlePaddle、PaddleOCR、OpenDataLoader、Java 17 及本机依赖；Marker 因 `Pillow<11` 与主 MinerU 环境冲突，保持独立 Worker。主应用经内部、路径白名单限制的 Marker 服务调用，不暴露宿主机端口。
- Hugging Face、PaddleOCR、PaddleX 和 Marker/Surya/Torch 缓存均为宿主机挂载；`scripts/export_parser_images_and_caches.sh` 导出三张镜像和模型缓存，`deploy/parser-runtime-migration.md` 约束新服务器恢复和数据库备份边界。聚焦 Marker/Paddle/解析器测试 39 通过、`py_compile` 和定向 `git diff --check` 通过；本机 Docker Engine 与 lockfile 联网解析不可用，镜像构建/导出和真实 PDF 容器验收仍待云端执行。
- 115.190.170.186 已作为生产 Compose 主机运行；日常开发应在本地功能分支完成并经 Git 发布，服务器只执行受控拉取、构建、迁移和重启，禁止在运行中的容器内直接编辑代码或安装依赖。
- 服务器访问应改为独立的非 root 运维用户和 SSH 密钥；root 密码登录在密钥验证成功后关闭。公网仅保留 22、80、443，继续禁止暴露 8000、5432、6379。
- 含迁移的更新必须先备份 PostgreSQL，再运行 migrate 服务；生产 .env 和卷数据不进入 Git 或同步包。未改动代码、运行配置、迁移或应用行为。
- 云端现象与本地不一致时，先保留请求 ID、时间窗、版本/镜像摘要、`docker compose config`、依赖/环境变量键名和健康状态；以隔离 staging 按同一提交和脱敏配置复现。按版本、配置、依赖/镜像、数据库迁移和数据、外部模型/网络、CPU/内存/文件系统逐层收敛；修复须先在 staging 验收，生产只发布已验证提交。
- 2026-08-07 上传任务 `2902b27d-a0fd-44d4-bdc8-f5fbe7f88386` 的附带日志显示 API/PG/LLM 预检均通过，但 Docling 在解析 PDF 时反复尝试下载 Hugging Face `docling-project/docling-layout-heron@main`，页面 OCR 报 `LocalEntryNotFoundError`；日志截断于下载阶段，尚无最终任务状态。判定为云端网络或 Hugging Face 缓存/挂载问题，非上传接口故障；未改运行代码或服务器配置。

## 23. 2026-08-07 持久登录修复与启动故障隔离

- 原始登录故障证据：`server.py` 启动同步调用默认 KB，LightRAG 初始化 `o200k_base.tiktoken` 时触发 `MemoryError`，连带 FastAPI lifespan 失败，导致登录接口不可用。
- 修复：启动阶段移除默认 KB/LightRAG 预热，RAG KB 改为首次查询或上传按需初始化；初始化失败只影响对应 KB，不再拖垮认证/API 启动。
- PostgreSQL refresh token 改为持久化 family 轮转：活动 JTI 显式写入 `revoked_at=NULL`；family advisory lock 下原子消费旧 token、注册新 token；旧 token 重放会撤销整个 family；登录、refresh、改密均返回完整用户和可立即使用的新 token 对。
- 前端会话持久化：启动恢复先校验 `/auth/me`，401/403 才 single-flight refresh；网络/5xx 保留 refresh 凭据待下次重试；API 请求遇到一次 401 会刷新并重放原请求，只有 refresh 明确 401/403 才清理会话；改密后保存服务端返回的新 token 对。
- 验证：`.venv` 后端聚焦测试 21 passed；前端 `npm run test:unit` 162 passed；真实 PostgreSQL HTTP 集成覆盖登录、连续 refresh、旧 token 重放 401、family 撤销和 `/auth/me`；`py_compile` 与本次作用域 `git diff --check` 通过。前端 `npm run build` 在受管环境中无输出挂起并超时，不能作为构建通过证据；完整仓库 diff 检查仍受既有 `PROJECT_SUMMARY.md:344` 尾随空白影响。

## 24. 2026-08-07 云端解析器镜像与缓存持久化验收

- 云端 `/opt/rag-anything` 已构建并切换 `raganything-app:parsers`、`raganything-marker:parsers`、`raganything-nginx:parsers` 三张镜像；Marker 容器通过健康检查，主应用最终为 `healthy`，PostgreSQL/Redis 保持运行，Nginx 已启动。
- 主应用镜像内已确认 `paddleocr==2.9.1` 与 `opendataloader-pdf==2.5.0`；独立 Marker 镜像内 `marker`、Torch 和 Pillow 均可导入。Marker 使用独立容器以隔离 `Pillow<11` 与主应用依赖。
- Compose 将 Hugging Face、PaddleOCR、PaddleX、Marker/Surya/Torch 缓存分别挂载到 `/opt/rag-anything/models/` 下；Docling Heron 模型已通过固定 revision 写入 Hugging Face 宿主机缓存（约 164 MB、16 个文件）。
- 完整备份包位于服务器 `deploy-artifacts/parser-runtime-20260807T085439Z/`：镜像归档约 7.49 GB，模型缓存归档约 159 MB；两项 `sha256sum -c` 均为 `OK`。真实 PDF 端到端解析 smoke 尚未在本次记录中完成。

## 25. 2026-08-07 后台多模态异常不再被错误标记为完成

- 2026-08-08 后续：云端日志确认 LightRAG 同时将 `./rag_storage_1` 用作 `working_dir` 与 `workspace`，因此 NanoVectorDB 实际文件为 `./rag_storage_1/rag_storage_1/vdb_chunks.json`。`document_quality.evaluate_content_readiness()` 现同时检查直接和嵌套路径并合并匹配 ID；新增回归后上传重试与标签测试共 58 通过，编译和本次 `git diff --check` 通过。云端尚未部署验收，且 `asyncpg.exceptions.ConnectionDoesNotExistError` 仍需用重新上传任务确认不会阻断实际向量写入。

- 云端 PDF 任务的 OpenDataLoader 解析已完成，但多模态后台写入出现 `asyncpg.exceptions.ConnectionDoesNotExistError`；旧任务注册回调会先把已失败任务从 pending 集合移除，却未读取异常，Worker 随后错误地完成收尾，留下文本块存在而向量块为零，自动标签只能拒绝该文档。
- 修复：已完成任务回调会消费并缓冲非取消异常；Worker 在等待循环开始、pending 为空返回前和已完成任务 gather 后消费该缓冲，任何后台写入失败都会终止 Worker，而不会写出假完成状态。已增加“任务在 drain 前失败且离开 pending 集合”回归测试。
- 本地验证：`tests/test_process_worker_lifecycle.py` 与 `tests/test_insert_content_list.py` 共 21 项通过；`process_worker.py`、`raganything/processor/batch_processor.py` 和包导出均通过 `py_compile`。待将这三个运行文件重新构建并部署云端 app 后，对失败 PDF 重新处理以生成向量；仅重试标签无法修复零向量文档。
- 部署阻塞修复：云端重建 app 时 `COPY . .` 曾尝试复制 `deploy-artifacts/` 内约 7.49 GB 的镜像归档并报 `no space left on device`；`.dockerignore` 已排除该目录，归档保留在宿主机且不会再进入 Docker build context。
- NanoVectorDB 标签门禁修复：云端 PostgreSQL 未安装 pgvector，KB `1` 使用 `./rag_storage_1/vdb_chunks.json`；原检查在 PG 向量表缺失时回退读取默认 `WORKING_DIR` 的 `./rag_storage/vdb_chunks.json`，导致已写入的非默认 KB 向量被误计为 0 并使自动标签失败。回退路径现按 KB 后缀推导；相关上传重试与标签测试 57 项通过，待重新构建 app 并在云端复验。
- 2026-08-09 embedding-cache loop safety: the async embedding wrapper now awaits cache I/O on the worker event loop and never moves the shared asyncpg pool to a thread-local loop. Read failures become cache misses and write/clear failures are no-ops with once-per-operation redacted diagnostics; synchronous cache methods remain safe no-ops. Local validation: 62 focused tests, `py_compile`, scoped `git diff --check`, and OpenSpec strict validation passed. Cloud acceptance remains pending: rebuild/restart `app`, upload a new small PDF, verify non-empty nested `vdb_chunks.json`, `vector_count > 0`, successful automatic tagging, and no relevant `ConnectionDoesNotExistError`. Existing zero-vector documents require re-upload or explicit reprocessing. The vision embedding HTTP 401 remains a separate credential configuration issue.

## 26. 2026-08-10 OpenSpec 与子代理存储边界澄清（无行为变更）

- OpenSpec/OPSX 提案与其 `proposal.md`、`design.md`、`tasks.md`、delta specs 位于仓库 `openspec/changes/`，提交后可由其他分支/克隆共享；未提交内容只属于当前工作区。
- 本项目 `.agents/skills/` 是项目级技能；用户级技能位于 `C:\Users\98014\.agents\skills\` 或 `C:\Users\98014\.codex\skills\`。子代理是当前任务的临时运行时上下文，不是可跨项目调用的持久资源；其代码编辑会即时出现在共享工作区，消息/会话记录不等同于项目能力。
- 仅将无项目状态、无敏感信息且跨仓库成立的通用技能、模板和个人工作规则放入用户级目录；OpenSpec 变更、项目规则/总结、部署与运行配置、迁移、凭据和服务器信息必须留在仓库或受控的密钥存储中。

## 27. 2026-08-10 NanoVectorDB Worker persistence hardening

- Production diagnosis found successful parsing, text insertion, embedding preflight, and graph extraction while the KB-specific `vdb_chunks.json` still contained an empty 49-byte NanoVectorDB payload. The stale local `storage_updated` flag caused NanoVectorDB to reload the older on-disk snapshot during Worker finalization and discard newly generated in-memory vectors.
- `harden-nanovectordb-worker-persistence` adds a Worker-only finalization mode. While the existing KB processing lock is held, it clears that stale flag only for `entities_vdb`, `relationships_vdb`, and `chunks_vdb`; a callback returning `False` raises the bounded `nanovectordb_persist_failed:<store>` failure. Normal application finalization keeps its prior behavior.
- The Worker uses this mode both for normal graph completion and failure cleanup. Callback exceptions propagate, so the Worker cannot report graph-building done after failed vector persistence.
- Local evidence: focused upload-retry and Worker-lifecycle tests passed (39), `py_compile`, scoped `git diff --check`, and `openspec validate harden-nanovectordb-worker-persistence --strict` passed. Cloud acceptance remains required: rebuild/restart `app`, upload a new small text PDF to KB `3`, then verify the nested `vdb_chunks.json` is non-empty, readiness has `vector_count > 0`, automatic tagging succeeds, and no relevant Worker persistence error occurs. Existing zero-vector documents still require re-upload or explicit reprocessing.

- 2026-08-10 deletion concurrency: LightRAG labels an acquired single-document pipeline as `Single document deletion`, but its concurrent-entry guard only accepts job names beginning with `Deleting`. The knowledge router now serializes `adelete_by_doc_id()` per KB before entering that vendor pipeline. Delete lifecycle tests passed (21); cloud acceptance requires deleting one failed legacy document from the UI after the next app rebuild.

## 28. 2026-08-10 用户级 OpenSpec/OPSX 技能同步（无应用行为变化）

- 已将 10 个无项目状态的 OpenSpec/OPSX 流程技能从项目 `.agents/skills/` 复制到用户级 `C:\Users\98014\.agents\skills\`，项目副本仍为唯一维护源；逐项 `SKILL.md` SHA-256、frontmatter 名称和唯一性均已核验，`openspec --version` 为 `1.4.1`。
- 用户级 `C:\Users\98014\.codex\AGENTS.md` 由空文件填充为最小通用安全/验证规则，不含本项目路径、RBAC、部署、迁移、凭据或强制 OpenSpec/多代理流程；未全局化依赖项目相对路径的 `impeccable`。本次未改动应用代码、配置、迁移或运行行为。
## 29. 2026-08-10 Worker 后 NanoVectorDB 快照覆盖修复（待云端验收）

- 云端复验确认 KB `3` 的嵌套 `vdb_chunks.json` 仍为 49 字节空快照；服务端 Worker 后 retire 旧缓存实例会覆盖 Worker 已写向量。
- `RAGAnything.finalize_storages()` 支持 `persist_vector_stores=False`；仅 Worker 后缓存失效跳过三个 file-backed VDB 回调，普通淘汰和关闭保持默认持久化。
- 本地定向验证：持久化/Worker 生命周期 40 passed，缓存回归 12 passed，`py_compile`、`git diff --check` 和 OpenSpec strict validation 通过。云端仍须重建 app、上传新 PDF，并确认嵌套向量文件非空、`vector_count > 0`、自动标签成功。
## 30. 2026-08-10 Worker 后缓存失效修复验收边界

`persist_vector_stores=False` 仅用于 Worker 写入后的旧缓存释放；普通缓存淘汰继续持久化向量。40 项 Worker/持久化测试与 12 项缓存回归通过，云端需重建 app 并重新上传新 PDF 验收。

## 31. 2026-08-10 视频自动处理（本地实现，待云端验收）

- 新上传的 `.mp4`、`.avi`、`.mov`、`.mkv`、`.webm` 由共享媒体扩展名 helper 自动派生内部 `enable_video=true`，并固定新任务快照为 v2；普通文件保持关闭视频处理器。保留的单文件和批量文件上传均按实际文件名判断。
- 个人、知识库、平台和环境配置中的旧 `enable_video` 保留为兼容读取但不再参与解析或公开投影；前端上传页、个人设置、平台设置和上传请求均移除视频开关。历史快照不迁移，显式旧值继续保持原语义。
- 本地验证：视频/设置/Worker 聚焦测试 100 项通过（2 项跳过），自动路由与共享后缀测试包含其中；前端单测 167 项通过；相关 `py_compile` 和 `git diff --check` 通过。上传任务回归另有 5 项既有 `text_embedding_identity_missing` 夹具失败，未归因于本变更；`npm run build` 在受限 Windows 环境中 120 秒无输出超时，构建未宣称通过；云端需重建 app 后上传短视频和 PDF 验收 Worker、向量和标签结果。

## 32. 2026-08-10 KB grant migration startup diagnosis

- Local startup initially failed in `pg_auth_repo._attach_allowed_kbs()` because `public.kb_access_grants` lacked `access_level`; migration history was applied through 032.
- `scripts/pg_migration_runner.py` now loads the project `.env` with `override=False`, matching `server.py`, so local PowerShell execution receives the configured `DATABASE_URL` without printing credentials. After backup acknowledgement, migrations 033 and 034 were applied successfully; the column now exists.
- Post-migration startup smoke reached `Application startup complete`; the process was stopped after verification. Focused migration/runner tests pass (16 passed, 1 skipped), with no remaining migration status or startup error.

## 33. 2026-08-10 Knowledge-base editing and permission review (no behavior change)

- Current KB editing is protected by two layers: role permission and KB object scope. Content changes (upload, document/chunk/tag changes, retry, multimodal reprocessing, ingestion and vision settings) require both `kb:write` and owner/super-admin scope or an explicit `operate` grant. A `read` grant permits viewing only.
- The KB editor drawer exposes display-name and member controls only from server-returned capabilities. Member management additionally requires `kb:manage`: super_admin can manage all KBs, dept_admin only owned or granted KBs, and teacher only owned KBs; assistant and student cannot manage members. Member grants accept only `read`/`operate`, cannot target the owner or super_admin, respect role hierarchy, and invalidate the member session after change.
- Verification: `tests/test_kb_member_access.py tests/test_kb_rbac_matrix.py` passed (22). The broader check including `tests/test_kb_ingestion_settings.py` had 25 pass / 2 fail because its mocks still replace the former read-scope helper while implementation now calls `verify_kb_operate_access`, causing an uninitialized local PG pool; this is a test-fixture drift, not runtime authorization acceptance. No source behavior was changed in this review.

## 34. 2026-08-10 Role-derived knowledge-base visibility (local implementation)

- `super_admin`, `dept_admin`, and `teacher` now receive read-only visibility of every knowledge base without adding rows to `kb_access_grants` or changing `allowed_kbs`. `assistant` and `student` remain limited to owned and explicitly granted knowledge bases.
- The same read scope applies to KB reads, list, batch statistics, switching, and document download. Content mutation remains gated by the endpoint permission plus ownership, super-admin status, or an explicit `operate` grant. A `read` grant and role-derived visibility do not allow upload, document/chunk/tag changes, graph editing, rename, member management, or deletion.
- `/api/kb/list` projects `read`, `operate`, `rename`, `manage_members`, and `delete` per KB. Detail, chunk, and delete UI controls consume that projection and fail closed after refresh or revocation. A prior dept-admin read-grant member-management path was tightened to require `operate`.
- Local verification: focused backend visibility/list/switch/stats/download tests passed (54); frontend unit/source-contract suite passed (169); `py_compile`, strict OpenSpec validation, and `git diff --check` passed. Authenticated PostgreSQL five-role sessions, migration fresh/upgrade/repeat verification, and browser acceptance remain required before deployment; no production migration or live role data was changed in this task.

## 35. 2026-08-10 Frontend multimodal controls removed

- The knowledge-base upload panel and personal settings page no longer expose image, table, or equation processing choices. Existing stored settings and historical task snapshots remain readable and unchanged.
- Both remaining frontend upload helpers now send `enable_image=true`, `enable_table=true`, and `enable_equation=true`; this affects new uploads created through the current frontend only. Direct backend API callers and legacy task semantics remain unchanged.
- Local verification for this change: frontend unit/source-contract tests passed (172), Vite production build passed, and scoped `git diff --check` passed. Browser acceptance, backend direct-API behavior, and production deployment acceptance remain unverified.

## 36. 2026-08-10 Non-file upload routes removed

- URL import, server-folder import, and pasted-content ingestion are removed from the knowledge-base upload UI, frontend API client, and backend router. Ordinary file and batch-file upload remain available.
- The removed backend surface is `POST /upload/folder`, `POST /upload/content`, and `POST /upload/url`; the folder whitelist setting and its route-only helpers are removed. Existing documents and persisted upload snapshots are not migrated or changed.
- Local verification: frontend unit/source-contract tests passed (172); focused backend RBAC, retained upload, and route-surface tests passed (32); upload-task regression tests passed (58, with 5 unrelated text-embedding-identity fixture cases excluded); router/test `py_compile`, Vite production build, and scoped `git diff --check` passed. Browser acceptance, direct API 404 confirmation, and deployment acceptance remain unverified.

## 37. 2026-08-10 Upload defaults and one-time override clarity (local implementation)

- The knowledge-base detail page now separates the long-term "知识库长期上传默认" from a local one-time chunking override. Normal file and batch uploads show the effective strategy and its KB, personal, or platform/system source, and omit `chunking_strategy` when no temporary override is selected.
- The temporary selector is collapsed by default, is explicitly expanded with accessible state, applies only to the next single-file or batch submit, and is cleared/collapsed after an accepted request. Rejected requests retain it for retry, and changing KB clears both the override and its expanded state. Image/table/equation processing remains fixed on for current frontend uploads.
- The batch upload router keeps an immutable request strategy and resolves each file independently. Queue payloads and per-task response rows carry that file's resolved strategy, preventing an earlier file's default resolution from becoming a later file's request override. No public endpoint, schema, migration, historical task snapshot, or direct API behavior changed.
- Local verification: frontend unit/source-contract tests passed (172); `tests/test_chunking_strategy_tracking.py tests/test_user_settings_resolution.py` passed (31); router `py_compile`, OpenSpec strict validation, and scoped `git diff --check` passed. `npm run build` produced no output and timed out at approximately 2 and 5 minutes in the managed Windows environment, so build and browser acceptance remain unverified.

## 38. 2026-08-11 Upload log chunking strategy verification (no code behavior change)

- The upload request and task snapshot for `4 系统设计.docx` both use `chunking_strategy=agentic`; the Worker records it as LLM intelligent chunking. The strategy asks the LLM to identify semantic boundaries, then merges segments to target `800` tokens with `100` tokens overlap; it is not embedding-similarity chunking.
- The log records 2 multimodal chunks and 3 chunks in final document status. A separate vision-embedding 401 authentication failure and terminal `upload_claim_lost` are processing/status boundaries and do not change the selected chunking strategy; final task success still requires task-status verification.

## 39. 2026-08-11 Local parser availability diagnostics (partial environment repair)

- MinerU command discovery now resolves `mineru.exe` beside the active virtual-environment interpreter for both installation probing and real parser execution, preventing a service process with a reduced `PATH` from incorrectly disabling an installed MinerU.
- The parser catalog now caches an additive, safe `reason` only for unavailable parsers. PaddleOCR, Marker, MinerU, and OpenDataLoader expose actionable local prerequisite errors; the personal-settings and KB-default selectors display that reason instead of a generic disabled option. Existing parser IDs, upload APIs, task snapshots, and persisted settings are unchanged.
- Local verification: MinerU 3.4.4 command and stable direct probe passed; Docling and OpenDataLoader direct probes passed, with the latter resolving its Java 17 runtime from the process environment. Focused parser/settings tests passed (60), frontend unit tests passed (173), `py_compile`, and `git diff --check` passed.
- This is not a complete five-parser environment acceptance: `paddlepaddle` and `marker-pdf[full]` are still absent from the local `.venv`. The approved package installation attempt timed out against PyPI, and the subsequent elevated retry was rejected by the approval service before execution. The FastAPI service was not listening on port 8001 during this verification, so authenticated `/api/users/me/settings/options`, image/PDF parsing smoke, browser UI, and production/container validation remain open until those dependencies are installed and the service is restarted.

## 40. 2026-08-11 Interrupted local parser dependency install cleanup (no application behavior change)

- The timed-out optional dependency installation left no completed PaddlePaddle or Marker package, no new wheel cache, and no `pip-*` temporary directory. Only the identified 107-byte pip version self-check record from the attempt was removed.
- Existing pip wheel caches, unattributable zero-byte temporary files, project files, virtual-environment packages, database data, and upload-task data were deliberately preserved. No parser availability, API, configuration, or deployment behavior changed during cleanup.

## 41. 2026-08-11 Frontend load response diagnosis and bounded repair

- Local HTTP smoke showed the running API health endpoint and unauthenticated auth endpoint responding in milliseconds; the reproducible frontend risks were stalled auth bootstrap, duplicate or overlapping client reads, and uncompressed production text assets rather than a local API baseline delay.
- Auth bootstrap and refresh now share an abortable 8-second request bound, preserving stored credentials for transient failures while preventing an indefinitely visible startup loader. Initial agent-thread selection avoids a redundant thread-list refresh; Monitor and AutoRepair dashboard reads are visibility-gated or cancel the preceding request before refreshing; hidden tabs skip epoch polling.
- Nginx now enables gzip only for text, CSS, JavaScript, JSON, XML, and SVG, leaving already-compressed font/media assets outside the explicit type list. No API, RBAC, database, migration, or persisted data behavior changed.
- Local verification: frontend unit suite 176 passed, Vite production build passed, scoped diff check passed, and local API health/auth smoke passed. Production Nginx compression headers, authenticated browser waterfall, slow-network recovery, and large-KB document pagination/load testing remain unverified; the detail endpoint still returns an unpaginated document list and needs a separately designed backward-compatible pagination change.

## 42. 2026-08-11 User-visible document-name cleanup

- Uploaded files retain their unique staged names for storage, retry, deduplication, and download lookup. A shared display-only helper now removes legacy 8-hex and current 32-hex prefixes at user-facing boundaries.
- Retrieval source caches, RRF, graph and tag-scoped contexts, agent document summaries, citation DTOs, video citations, document-task display, citation fallback, and download response filenames show the original filename without changing persisted `file_path` values.
- Local verification: 70 focused tests passed, including display normalization, source-cache reconstruction, RRF/graph/tag retrieval, structured and video citations, and prefixed-file download resolution; `py_compile` and scoped `git diff --check` passed. Browser and deployed-service acceptance remain unverified.

## 43. 2026-08-11 Large knowledge-base document summary pagination

- `GET /api/knowledge/document-summaries` now provides PostgreSQL-backed, case-insensitive display-name search, exact totals, stable pagination, deduplication, bounded runtime-task/upload-status overlays, and page-only tag health. The legacy `/api/knowledge/documents` full-list contract is unchanged; JSON storage remains a compatibility fallback outside the large-KB performance guarantee.
- The knowledge-detail page now uses auth/KB/page/search-scoped caches, 250 ms debounced cancellable server search, server pagination metadata, page clamping, cross-page selection, and KB-wide cache invalidation after document and upload-task mutations. Same-name active task phases are preserved for legacy persisted rows without task provenance.
- Verification: backend focused suite 56 passed; frontend utility suite 179 passed; `py_compile`, scoped `git diff --check`, OpenSpec strict validation, and Vite production build passed. A warmed local PostgreSQL fixture with 10,000 synthetic rows returned 50-row pages with mean 188 ms and P95 190 ms across 30 calls; the matching `EXPLAIN (ANALYZE, BUFFERS)` completed in 123 ms. No index migration was added because the measured plan is below the 1-second release gate.
- Remaining acceptance boundary: authenticated browser regression, deployed-service/Nginx behavior, and production PostgreSQL multi-role acceptance remain unverified. The benchmark used a unique disposable workspace and removed only its synthetic rows.

## 43.1 2026-08-12 Knowledge-detail request lifecycle optimization

- `optimize-knowledge-detail-request-lifecycle` adds cache-owned, reference-aware cancellation for knowledge-detail document-page and statistics reads. A caller can abandon an obsolete KB/page/search request; the underlying fetch is aborted only after its final consumer releases it. The statistics request remains independently shared across pages, and abort/failure/invalidation/auth-generation races cannot populate the scoped cache.
- `GET /api/knowledge/document-summaries` no longer performs global terminal-task cleanup during ordinary reads. Its runtime-task read is now scoped to the authorized KB and bounded to 200 active rows. Object-level authorization remains a FastAPI dependency before route data work; legacy `/api/knowledge/documents` behavior is unchanged.
- Verification: two frontend and one backend expert reviews completed; frontend unit suite 206 passed, focused document-summary/runtime-task backend suite 6 passed, strict OpenSpec validation and scoped `git diff --check` passed, and the final Vite production build completed in 7.27 seconds. Tests cover one-consumer survival, final-consumer abort of document and statistics requests, cross-page statistics sharing, invalidation abort, pre-aborted callers, cache-registry isolation, auth-generation invalidation, KB-bounded runtime tasks, and no read-time cleanup.
- Remaining acceptance boundary: no authenticated browser trace or deployed-service measurement has been performed for this follow-up. The cloud host still has the previous healthy app container because the earlier full-image rebuild was interrupted while downloading dependencies; it must be rebuilt and health/browser-checked before release acceptance.

## 44. 2026-08-11 云端公开问答演示窗口

- `public-demo-qa-window` 已落地迁移 `035_public_demo_shares.sql`、SHA-256 令牌哈希、固定 agent/KB、PostgreSQL 限流与并发租约、超级管理员创建/撤销、匿名 bootstrap/SSE、无会话持久化、撤销二次校验和短时受控媒体预览。
- 前端新增独立 `/demo/:shareId#token` kiosk 页面；令牌只从 fragment 读取并通过 `X-Demo-Token` 发送，匿名请求省略浏览器凭据，来源仅显示脱敏文档名，媒体仅接受同源短时 grant。
- 本地证据：后端公开演示与迁移测试 26 passed；前端 `npm run test:unit` 184 passed；OpenSpec strict 与 `git diff --check` 通过。`npm run build` 在受管 Windows 环境 124 秒无输出超时，构建未验证。
- 云端边界：确认 PostgreSQL 备份后执行迁移，重建 App/前端镜像，验收真实云端 KB 的 SSE、引用、媒体、撤销、限流与 Nginx 同源路由。2.1 的认证/演示查询路径尚未提炼为共享服务，归档前需补齐或明确接受实现差异。

## 45. 2026-08-12 本地公开演示迁移恢复

- 本地 PostgreSQL 在执行迁移前已创建可恢复的压缩备份并完成校验；项目迁移执行器随后成功应用唯一待处理的 `035_public_demo_shares.sql`。该迁移仅新增 `demo_shares` 及活跃链接索引，未修改既有业务表或数据。
- 复核显示迁移清单已到第 38 项且链路为 current；未携带认证信息访问 `GET /api/demo/shares` 现在返回预期的 `401`，此前由缺少 `demo_shares` 引起的 `UndefinedTableError` / 500 已消除。前端管理入口 `/admin/demo-shares` 的 SPA 响应为 200。
- 未创建演示分享、未发起真实 RAG/SSE 问答，未改动云服务器或云端知识库。发布前仍须解决公开演示并发状态在异常重启后的回收，以及 OpenSpec 2.1 的认证/演示共享查询执行层，再执行云端备份、迁移和真实 KB 验收。

## 46. 2026-08-12 公开演示窗口视觉与阅读体验

- 独立 `/demo/:shareId` kiosk 页面升级为适合投影展示的深蓝信息顶栏、明确的助手欢迎态、对话身份标识、受限宽度的 Markdown 回答排版和来源编号卡片；底部输入区域与回答列对齐，桌面不再出现横跨全屏的控制条，移动端保留安全区、44px 操作目标和单列布局。
- 演示回答现在使用默认安全的 Markdown 渲染，支持标题、强调、列表、代码、引用与分割线；不启用原始 HTML，链接不作为外部跳转渲染。令牌 fragment、同源受控媒体 URL、匿名请求与 SSE 行为均未改变。知识库解析/分块仍明确为“新上传默认”的只读状态。
- 本地验证：前端单元测试 184 passed，Vite 生产构建通过，公开页安全渲染契约和 scoped `git diff --check` 通过。浏览器 CDP 前置脚本在本机不可用，因此实际桌面/移动截图、真实分享 SSE 与受控媒体交互仍需在可用浏览器或云端环境中验收。

## 47. 2026-08-12 公开演示滚动跟随修复

- 演示问答区不再在每个流式 token 到达时无条件滚到底部；用户滚轮上滑离开底部后会暂停自动跟随，出现“新回答”按钮，点击后恢复到底部跟随。发送新问题时会重新启用跟随，固定底部输入栏和 Enter 发送行为不变。
- 本地验证：前端单元测试 186 passed，公开演示滚动/固定输入源码契约通过，scoped `git diff --check` 通过；真实浏览器滚轮和移动触控验收仍受本机 CDP 不可用限制。

## 48. 2026-08-12 撤销教师与学生演示首屏优化

- 按用户要求移除上一轮新增的云端在线状态、教师/学生定位、课堂推荐问题及其专用样式和源码契约测试；普通欢迎页、深蓝顶栏、Markdown、来源/媒体、滚动跟随、固定输入框和 Enter 发送行为保留。
- 本地验证：前端单元测试 186 passed，OpenSpec `public-demo-qa-window` strict 校验通过，相关文件 `git diff --check` 通过。未改变后端、令牌、SSE、媒体安全逻辑或云端部署状态。

## 49. 2026-08-12 学习对话版公开演示界面

- 公开演示页改为学习对话布局：顶部拆分为品牌/知识库主信息与低权重只读设置；用户问题增加身份标识；回答列适度加宽并压缩重复留白；代码块和长内容改为更轻的阅读样式。
- 来源与受控图片/视频统一收进可访问的“依据与资料”折叠区，仍只消费 SSE 返回的来源和 `controlledDemoMediaUrl` 结果；未改变令牌、SSE、媒体授权、固定输入框、Enter/IME、滚动跟随或后端行为。
- 本地验证：前端单元测试 188 passed，OpenSpec strict 与 scoped `git diff --check` 通过。`npm run build` 在受管 Windows 环境约 124 秒无输出超时，本轮构建未验证；浏览器桌面/移动截图和真实云端问答仍未验收。

## 50. 2026-08-12 公开演示实体关系紧凑渲染

- 公开演示页将连续的单行 fenced 实体、关系箭头和单行 fenced 实体识别为只读关系条，紧凑渲染为“实体 → 关系 → 实体”；未参与关系的短实体渲染为小标签。多行或含代码结构的 fenced block 保持原 Markdown 代码块，不改变回答语义。
- 本地验证：前端单元测试 191 passed，含连续实体关系、普通多行代码和非法标记的格式化器测试；OpenSpec strict 与 scoped `git diff --check` 通过。浏览器实际长回答视觉验收和云端环境仍未验证。

## 51. 2026-08-12 修正公开演示箭头关系格式

- 根据真实问答输出补充识别“单行实体代码块 → 单独箭头段落 → 单行实体代码块”的格式；该格式现在与带关系文字的三元组一样渲染为紧凑关系条。之前页面仍逐行显示不是缓存导致，而是原匹配规则未覆盖这种实际输出形态。
- 本地验证：前端单元测试 192 passed，新增箭头关系回归测试，`git diff --check` 通过。开发服务器通常热更新，已构建版本需要重新构建前端资源并刷新/重启应用；浏览器和云端部署验收仍未完成。

## 52. 2026-08-12 公开演示实体紧凑判定修复

- 收紧公开演示格式化器：只有单行且不含关系分隔符的实体才会渲染为紧凑标签或关系条；多行代码块和含分隔符的值保持普通 Markdown/代码输出。
- 本轮仅修改演示端展示规则及其测试，不改变智能体配置、知识库数据、RAG 检索、SSE 协议、媒体授权或后端行为。
- 本地验证：前端单元测试 193 passed；`npx openspec validate public-demo-qa-window --strict` 通过；scoped `git diff --check` 通过。已构建资源、浏览器/移动端视觉验收和云端部署仍未验证。

## 53. 2026-08-12 正常智能体关系紧凑展示

- 新增 `compact-agent-relation-display` 前端变更：登录后的正常智能体聊天页现在仅在助手回答完成且成功时，将完整的“实体代码块 - 关系箭头 - 实体代码块”压缩为关系条；不再把独立短代码、SQL、命令、配置、行内代码或半截流式代码误判为实体。
- 转换只发生在展示层，原始 `m.content`、SSE token、会话保存/编辑/重试、引用和媒体行为均不变；正常智能体使用独立的 `agent-chat-relation` 样式，不复用公开演示 kiosk 的类名或权限边界。
- 本地验证：前端单元测试 `201 passed`，其中新增关系格式化/源代码契约测试 8 项；OpenSpec `compact-agent-relation-display` strict 校验通过；相关文件 `git diff --check` 通过。Vite 构建、真实浏览器桌面/移动端和云端部署验收仍未验证。

## 54. 2026-08-12 发布可信度与可检索性首批收敛

- 新增 active change `production-readiness-and-durable-ingestion`：PostgreSQL 严格就绪检查要求有效文本块与完整向量覆盖；缺失文本、无效内容、向量缺失或权威存储不可用会进入可恢复的 `retrieval_readiness` 重试，保留 task claim owner/generation 围栏，不能标记 `completed`。图谱、标签和可选多模态后处理不再把已具备检索工件的上传改为失败；标签问题记为 `degraded` 并保留修复入口。
- 增加受后端权限保护的 `GET /knowledge/retrieval-health` 与 `POST /knowledge/documents/{doc_id}/repair-retrieval`：前者要求 KB read scope + `kb:read`，后者要求 KB operate scope + `kb:write`，复用 `(kb_name, doc_id, stage)` 幂等 repair job。未新增或改写历史迁移。
- 新增只读 `scripts/release_candidate_inventory.py`。本次盘点结果为：35 个 OpenSpec 工件已归属、3 个共享序列化资产（项目总结、migration manifest、Nginx）、86 个未归属改动、2 个生成物候选；因此当前 dirty worktree 不能作为单一发布候选，需按 OpenSpec/功能边界拆分并串行处理共享资产。
- 新增 `scripts/run_isolated_release_acceptance.py` 与 `docs/isolated-release-acceptance.md`。runner 强制 non-production、隔离 target/目录、显式源码根目录、fresh/upgrade/repeat/intentional-failure migration、五角色、Worker、health 与始终执行的 cleanup 阶段；任一失败或跳过均输出脱敏 `not-releasable` 证据。它不执行生产迁移，不把外部模型、视频、浏览器 UAT 或生产批准误报为完成。
- 代码级证据：先前聚焦回归 8 项通过；本轮 `py_compile`、OpenSpec strict 和 scoped `git diff --check` 通过。随后本机在导入 LightRAG 的 `pypinyin` 词库时发生 `MemoryError`，使后端 pytest 收集受阻；这不是通过证据。真实隔离 PostgreSQL/Worker、migration 四路径、五角色直接 API、浏览器/视频和生产批准均未执行，仍为发布前必需验收边界。
- 追加验证：生产就绪测试 13 项、文档健康/repair 23 项、五角色 KB 权限 39 项、上传 claim/取消/重试 17 项通过。旧上传回归夹具补齐了无密钥的 `text_embedding_identity`，未放宽生产快照校验。新增修复端点对文档 ID 前缀采用精确优先、唯一前缀规则，歧义返回 409；验收 runner 的证据错误信息会移除绝对路径，并始终在隔离工作目录执行 cleanup。真实迁移/PG/Worker 验收仍未执行。
## 55. 2026-08-13 KB detail capabilities fallback

- `frontend/src/hooks/useConfirmedKnowledgeBase.js` now normalizes missing or invalid KB `capabilities` to an empty object, preserving fail-closed permission checks and preventing the detail page crash when reading `operate`.
- Frontend unit tests and Vite production build passed locally. Cloud static asset deployment is pending because SSH to `115.190.170.186:22` timed out; no backend or database changes were made in this step.
## 56. 2026-08-13 capability guard deployment diagnosis

- Added optional chaining at the three KB detail write-capability read sites and updated their source-contract tests; frontend unit tests: 206 passed, Vite build passed.
- Cloud HTTP currently serves old bundle `/assets/index-Dwxog5Mk.js`; local build serves `/assets/index-ErAIT5tC.js`. The new archive SHA256 is `34472E53FB0FF34B87004AAD154B0E00DE98A84703B64724F8D37488561B53E2`, but SCP/SSH timed out, so the new static assets are not deployed yet.
## 57. 2026-08-13 online asset overwrite evidence

- Read-only HTTP inspection shows the cloud index still references `/assets/index-Dwxog5Mk.js`, and the lazy `KnowledgeDetailPage` chunk still contains plain `capabilities.operate` with no optional guard. This confirms the current browser error is from an old static bundle; force refresh cannot fix an unchanged server asset.
- A concurrent cloud deployment/rebuild can overwrite the Nginx static image or replace the served `dist`; deployment must be serialized with other sessions before retrying.

## 58. 2026-08-13 selected release deployment attempt

- 已向云端 `/opt/rag-anything` 上传本批选定的运行文件，并在服务器创建源码/当前镜像备份；逐文件 SHA-256 对比一致。未上传或覆盖 `.env`、PostgreSQL/Redis 数据卷、上传文件、`rag_storage`、输出目录和模型缓存，未执行生产迁移。
- 按用户授权清理 Docker 悬空镜像和未使用构建缓存：释放约 `1.58 GB` 构建缓存及少量悬空层；未使用 `image prune -a`、`volume prune` 或带 `--volumes` 的清理。清理后根分区可用空间约 `1.9 GB`，后续构建期间约 `1.7–1.8 GB`。
- 已为当前运行镜像增加独立的 `predeploy` 回滚标签。`raganything-app`、PostgreSQL、Redis、Marker、Nginx 均保持运行；app 健康检查持续为 `healthy`，本机 `/api/health` 返回 `200`。
- `docker compose build app` 曾执行依赖安装，但最终未产生新镜像，且 app 未重启；因此本次不能记为代码已发布。生产仍运行原有 `kb-pagination-recovery-20260812` 镜像。Compose 日志未见由本次操作引起的启动异常；剩余构建缓存约 `2.07 GB`，可在下次受控构建前重新评估磁盘空间。
- 当前结论仅覆盖远程文件同步、Docker 清理、旧容器健康和 HTTP smoke；真实 Worker、上传到向量检索、五角色浏览器/API、迁移 fresh/upgrade/repeat/failure 及生产批准仍未完成。

## 59. 2026-08-13 production disk reclamation

- 在用户确认后，生产服务器仅清理了未使用的 Docker 构建缓存、五个经容器引用核验的历史应用镜像、一个三天前成功退出的迁移容器及其未再被容器引用的镜像层。未删除 PostgreSQL/Redis 卷、上传、`rag_storage`、输出、模型缓存、运行容器或业务数据；两份约 7.49 GB 的 parser-runtime 归档因 SHA-256 不同而保留。
- 实际回收：构建缓存约 2.068 GB、随后镜像/历史容器约 3.676 GB；根分区可用空间从约 1.8 GB 升至约 23 GB。Docker 的 `image prune -a` 会删除未被容器引用的带标签镜像，因此原 `predeploy` 标签被移除；已立即将当前健康 app 镜像重新固定为 `rollback-current-20260813T103000Z`。
- 终检：app/Marker/PostgreSQL/Redis/Nginx 均运行，app 与 Marker healthy；app 直连和 Nginx `/api/health` 均为 HTTP 200。当前运行版本未切换，仍为 `kb-pagination-recovery-20260812`；本次仅完成容量恢复，不构成新代码发布、Worker/PG 验收或生产迁移批准。
## 60. 2026-08-13 production mirror-build final result

- The selected source is present in `/opt/rag-anything`, but the mirror-backed `docker build --target default -t raganything-app:parsers` ended with status `1` at the OpenDataLoader validation layer: `java -version` did not satisfy the required Java 17 check. No `raganything-app:parsers` image was produced and `app` was not switched.
- The existing `raganything-app:kb-pagination-recovery-20260812` container remains `healthy`; direct `http://127.0.0.1:8000/api/health` and Nginx `http://127.0.0.1/api/health` both returned HTTP 200 after the failed build. No production migration, data-volume change, Worker ingestion/retrieval, browser/RBAC acceptance, or production approval was performed. Root free space after the failed build was about 9.6 GB; the rollback tag remains the release recovery point.
-## 61. 2026-08-13 app-only build and rollback

- Fixed the Dockerfile Java 17 self-check regex from double escaping to the correct literal-dot ERE. A temporary app-only Dockerfile (frontend/base/default only) built \`raganything-app:parsers\` successfully with image ID \`sha256:3eb524d990a2b35c50b675a6f55016051bae557a4bb5b51231460f399ca2342e\`; the temporary file was removed afterward.
- The app-only image was switched with \`docker compose up -d --no-deps --no-build app\`, but startup failed because the selected remote source set was inconsistent: \`knowledge.py\` imported \`has_default_kb_read_access\`, which was absent from the deployed \`dependencies.py\`. The new container became unhealthy/restarting and returned direct health \`000\` / Nginx \`502\`.
- The immutable rollback tag \`raganything-app:rollback-current-20260813T103000Z\` was retagged and the app was restored with the same \`--no-deps --no-build\` boundary. Final state: image ID \`sha256:9ed3118702640006e748b34f64b7adc10cb63a862eeaaa993c5ed766a590bca7\`, container healthy, restart count 0, direct and Nginx health both HTTP 200. No migration or data-volume change was performed; Worker, retrieval, five-role browser/API, and production approval remain unverified.

## 62. 2026-08-13 workspace convergence snapshot

- All source, tests, migrations, OpenSpec artifacts, deployment configuration, and documentation changes in the working tree were consolidated into one Git snapshot at the user's request. Reproducible root-level test output files and an unrelated malformed temporary file were removed instead of versioned; local environment files, runtime data, uploads, and model caches remain ignored.
- This commit establishes a complete source boundary for the next cloud release archive. It does not itself deploy code or change the production acceptance boundary recorded above.

## 63. 2026-08-13 committed-source cloud release

- Commit `65531a0` was packaged with `git archive`, uploaded to the production host, and verified against its SHA-256 before extraction into an isolated release directory. App and Nginx candidates were built from that same source; the app import preflight confirmed the KB access dependency and router import, and Nginx configuration syntax passed with the Compose `app` hostname mapped for standalone validation.
- The current app and Nginx images were each preserved under `rollback-before-65531a0459cf` before replacement. App switched first and remained healthy for more than three minutes with restart count zero; Nginx then switched. Direct and reverse-proxy `/api/health` checks both returned HTTP 200. The staged committed source was subsequently copied to `/opt/rag-anything` and verified, without copying `.env`, volumes, uploads, indexes, outputs, or model caches. No production migration was run.
- This proves image build, startup, source synchronization, and HTTP health only. Worker ingestion/retrieval, real migration paths, five-role direct API/browser checks, video E2E, and production approval remain separate acceptance work.

## 64. 2026-08-13 production Docker image reclamation

- After explicit approval, unused Docker build cache, superseded release/rollback image tags, staging directories, release archive, and finally all images not referenced by containers were removed from the production host. The cleanup did not touch environment files, PostgreSQL or Redis volumes, uploads, indexes, outputs, model caches, running containers, or application data.
- Observed root filesystem availability increased from approximately 7.3 GB to 34 GB (67% used). Immediately after the image prune, the five running service containers remained up; app direct and reverse-proxy health endpoints both returned HTTP 200.
- The removed rollback tags mean reverting to the preceding version now requires rebuilding it from source. Build cache was also removed, so a subsequent image build may download dependencies again. This is operational capacity evidence only; it does not substitute for Worker, migration, RBAC, video, browser, or production-approval acceptance.

## 65. 2026-08-14 frontend opaque identifier display audit

- Read-only audit found that KB internal names can be rendered as visible fallback text on KB cards/selectors and in agent, chat, and demo-share views; agent cards also show an internal agent ID. Prefer the maintained KB `label`/display name for all user-facing output, remove the agent-card ID, and retain internal identifiers only as route/API values or explicitly marked, copyable technical details for authorized administrators. Graph entity views fall back from `label` to `id`; the backend should reject opaque 32-hex values as entity display values or supply a separate display name instead of relying on a frontend-wide masking rule. Do not mask or remove the one-time public-demo URL token: it is an intentional capability secret, is not persisted in plaintext, and must be copied by its creator.
- No persistent behavior change was made; this conclusion is source-level only and does not establish whether existing production records are missing display labels.

## 66. 2026-08-14 user-facing opaque identifier removal

- User-facing KB cards, selectors, agent directory/chat, demo-share management, and public-demo bootstrap now resolve a separate safe KB display name. Empty legacy metadata, or a display name equal to a 32-character hexadecimal internal workspace name, renders as `未命名知识库`; the raw name remains only the API, route, and React-key identifier. Agent directory cards no longer render agent IDs, while newly created demo tokens retain their intentional one-time copy flow.
- `GET /agents` and demo-share responses include `kb_display_name` (plus the share-list `agent_name`) so clients do not infer presentation text from internal fields. Automatic graph entities that exactly match 32 hexadecimal characters and their automatic edges are filtered before user graph edits merge; manually created business-code entities and relations remain visible. Missing graph labels render as `未命名实体`, including relation-side references.
- Source-level verification passed: focused Python tests (22), all frontend unit tests (211), frontend production build, and `git diff --check`. This excludes browser interaction, live PostgreSQL graph records, and production deployment acceptance; monitor and health-probe technical identifiers were intentionally left out of scope.

## 67. 2026-08-14 production build cancellation and cache reclamation

- The abandoned mirror-backed build was stopped before it could complete the unintended CUDA-enabled PyTorch dependency download. Docker build cache cleanup reclaimed `5.189 GB`; root filesystem availability increased to about `20 GB` (`81%` used). No image, container, volume, database, uploads, indexes, outputs, model cache, or environment file was removed by this cleanup.
- Final operational smoke: the app health endpoint returned HTTP 200 with approximately `19.5 GB` reported free. This is capacity and availability evidence only; it does not deploy the pending source, establish a CPU-only base image, or replace Worker, browser, migration, RBAC, or production acceptance.
- A stopped failed-build container and its untagged image were subsequently removed. The app health endpoint remained HTTP 200 and root free space was about `19.8 GB`; image-layer sharing meant the recovered filesystem space was smaller than the image's displayed nominal size. The older `full-2026-08-12-090934` source backup was then explicitly deleted, increasing root free space to approximately `34 GB` (`66%` used). The newer `release-65531a0-2026-08-13-174911` backup remains retained; no data volume or running container was removed.

## 68. 2026-08-14 CPU runtime release foundation

- Added generated, hash-verified Linux/Python 3.11/x86_64 dependency locks for the app and isolated Marker runtime. The app lock resolves `torch==2.13.0+cpu` and `torchvision==0.28.0+cpu`; neither lock contains NVIDIA, CUDA, or Triton distributions. Docker now separates the dependency-only `app-runtime` and `marker-runtime` targets from source overlays, installs locks with the dedicated PyTorch CPU index, and runs a CPU/parser runtime acceptance script during image construction.
- Source-level verification passed: `scripts/verify_cpu_runtime.py` compiled, four CPU runtime contract tests passed, OpenSpec `cpu-only-fast-release` strict validation passed, and `git diff --check` passed. Local Docker is unavailable and non-interactive SSH authentication to the production host is not configured, so Linux image builds, parser fixture conversion/model-cache checks, production GPU/index checks, and any service switch have not occurred. The commit-only fast release and rollback automation remain planned tasks in the active change; no cloud code, container, data, migration, or volume was changed by this work.

## 69. 2026-08-14 CPU runtime transfer retry policy

- The first controlled remote `app-runtime` build reached the hash-verified CPU dependency installation and then failed with a `ReadTimeoutError` while downloading from `files.pythonhosted.org`; no candidate image was accepted and no container, migration, volume, or cloud source switch occurred. The host retained about 31 GB free and both direct and reverse-proxy health checks stayed HTTP 200.
- `Dockerfile` now exposes transport-only build arguments `PIP_NETWORK_TIMEOUT` (default 600 seconds) and `PIP_NETWORK_RETRIES` (default 12), consumed by both app and Marker hash-verified installs. Package locks, index selection, hashes, and CPU-only CUDA-exclusion policy are unchanged. Focused runtime contract tests (4), strict OpenSpec validation, and `git diff --check` passed locally; the renewed remote runtime build remains required before the base can be accepted.

## 70. 2026-08-14 CPU runtime lock availability correction

- The renewed remote build completed CPU dependency downloads through the PyTorch CPU wheel, then failed because the committed `uvicorn==0.52.3` lock entry has no Python 3.11 distribution on the configured indexes. Official PyPI metadata confirms `uvicorn==0.52.1` supports Python 3.11 and provides the verified wheel and source hashes used in the replacement lock entry. This was a lock availability defect, not a CUDA, parser, disk, or service-start failure; no candidate image was accepted or switched.
- The app CPU lock now pins `uvicorn==0.52.1` with official hashes, and the CPU runtime contract test rejects the unavailable `0.52.3` pin. The app and Nginx production containers remained healthy throughout; a fresh committed archive and a renewed isolated runtime build are still required for production runtime acceptance.

## 71. 2026-08-14 isolated PyTorch package source

- The third CPU runtime build reached the middle of the dependency lock and then timed out again at `files.pythonhosted.org` despite using the Tsinghua index. The failure was caused by using the official PyTorch CPU repository as a general `--extra-index-url`, allowing ordinary packages to select links outside the configured mirror; no image was accepted or switched and production health stayed HTTP 200.
- Added `requirements.cpu-pytorch-linux-py311-x86_64.lock` and split app/Marker installation into a hash-verified, `--no-deps` CPU Torch/Torchvision step from the official CPU index followed by a hash-verified general lock step using only `PIP_INDEX_URL`. Focused runtime contract tests (4) and strict OpenSpec validation pass; a new complete archive and isolated build are required.

## 73. 2026-08-15 commit-only fast-release automation

- Implemented thin app and Nginx overlay Dockerfiles plus `deploy.ps1` and a locked remote rollout script. A release is built only from an explicit full Git commit using `git archive`; dependency, Docker/Compose, migration, model-manifest, frontend runtime/lock, and release-tool changes are rejected before upload. The release payload excludes environment files and persistent runtime data.
- The remote routine verifies the archive checksum and immutable runtime image IDs, rejects concurrent Docker builds and insufficient disk without cleanup, runs an app import smoke, switches only app and then Nginx, checks direct and reverse-proxy health plus restart count through a stability window, and restores the captured app/Nginx images after a post-switch failure. It never invokes migrations, pruning, volume changes, or Marker/PostgreSQL/Redis replacement.
- Local evidence: CPU runtime and fast-release contract tests passed (9), OpenSpec strict validation passed, and `git diff --check` passed. The accepted production app base is `raganything-app-runtime:cpu-de7a773` at image ID `sha256:ade5bf64a9a9c7d6046a53d69aaa1895ab1723067b0d8da2f9a06d497ba333ca`; no fast release has been executed yet because the local SSH key configuration and immutable Nginx runtime selection remain operator setup, and Marker runtime production acceptance remains pending.
- Windows PowerShell 5.1 resolves the default deployment configuration only after the script begins executing, so `deploy.ps1` derives its script root at runtime rather than from a parameter default. Focused tests now cover this invocation boundary.
- Windows `tar` could not extract this repository's Git archive containing Chinese artifact paths, before any server upload. The local staging path now uses `git archive --format=zip` with `Expand-Archive`; a disposable extraction verified all 6,646 files including `server.py` and `frontend/`.
