# RAG-Anything 项目核心总结

> 本文件是项目任务的首要导航。实际代码、迁移、运行配置和 OpenSpec 规格优先于本摘要；敏感值、用户数据和运行日志不得写入。

## 0. 元信息与使用规则

| 项目 | 当前值 |
|---|---|
| 最后核验日期 | 2026-08-21（Asia/Shanghai） |
| 核验分支 | `feature/custom-enhancements` |
| 基准提交 | `52e0482714de` |
| 工作区状态 | 有未提交改动；未提交实现不得视为已发布 |
| 维护上限 | 不超过 350 行、30 KB；近期任务不超过 15 条 |

事实优先级：当前实现与验证结果 > `openspec/specs/` > active change > 归档资料 > 旧文档。

生命周期：启动前完整阅读本文件并定向核验源码；收尾由协调者更新事实和追加记录；无持久行为变化也记录结论。OpenSpec apply 完成验证后必须同步本文件，archive 前再次确认。

## 1. 项目定位与用户

RAG-Anything 是面向教育和专业实训的多模态知识库与智能体平台，提供文档解析、分块、向量/图谱检索、智能体问答和领域应用。用户角色为 `super_admin`、`dept_admin`、`teacher`、`assistant`、`student`。中文为主要界面语言，目标 WCAG 2.2 AA。

## 2. 当前能力与状态

### 稳定现状

- FastAPI 后端、React/Vite 前端、PostgreSQL 认证与业务仓库、Redis/向量/图谱外部存储。
- 五级 RBAC、JWT、密码、审计、Token 撤销；`is_admin` 仅由 `super_admin` 派生。
- 知识库上传、异步 Worker、文档/分块/标签/图谱管理、混合检索与引用。
- 智能体模板、CRUD、KB 绑定、会话和 SSE；共享智能体不共享会话历史。
- 账户目标层级事务锁、WebSocket JTI/session-generation 复核、任务 owner 定向事件和脱敏监控通道。
- Worker 进程组回收；容器 `/api/live` 与 `/api/ready` 分离，应用不直接暴露宿主端口。
- PostgreSQL advisory-lock 单会话迁移执行，TLS URL 参数保留且诊断脱敏。
- CORS 显式允许 `PATCH`；Agent SSE 已部署首事件确认、脱敏心跳、客户端首事件/空闲超时及 Nginx 无缓冲转发。
- Legacy 文档 readiness 仅提供只读预览；Prometheus scrape inventory 已纳入仓库。

### 进行中

- Agent SSE 空流修复已通过独立提交和快速发布；其余安全与流式韧性并发改动仍需各自受控发布。
- 知识库成员/显示名称、解析器覆盖、个人/平台设置、视觉模型、视频语义索引、库存问答、分块分页等 active change 仍需按各自验收边界推进。
- 项目总结已压缩；后续记录应替换旧记录而不是无限追加。
- `optimize-isolated-query-capacity` 已开始：测试专用、随机 key 保护的 app 内 cProfile 工具和合约测试在未提交工作区，尚未完成 Linux runtime 归因；不得将其部署到生产或当作容量改进。
- `production-readiness-and-durable-ingestion` 已在干净 detached 候选 `f8af072` 上通过独立 pgvector/Redis/mock/App/Worker/Nginx 验收：fresh/upgrade/repeat/intentional-failure 迁移、health、五角色矩阵、Worker 上传到 PostgreSQL text/vector、retrieval-health、认证查询引用及标签清理均通过。证据为脱敏临时文件；外部 provider、视频、浏览器 UAT 和生产批准仍明确 deferred，不能据此宣称生产验收。

### 计划

- Prometheus staging scrape/target 与告警演练。
- 受控环境的真实 Worker、浏览器、五角色 API/WS、Docker PG 抖动、迁移并发/TLS 验收。
- 历史 readiness 仅在备份确认、终态和证据充分时执行最小回填；生产数据本轮不回填。

### 已废弃

- 旧三角色模型、SQLite 认证、`users.email`/`DEFAULT_ADMIN_EMAIL`、旧 `/upload`/`/query` 描述均不代表当前实现。
- DAG 工作流页面、接口、执行器、权限和持久化已从当前代码移除；`037_remove_dag_workflow.sql` 会不可逆删除历史定义与运行记录。生产执行前必须核验可恢复备份，并完成隔离 PostgreSQL fresh/upgrade/repeat/failure 验收。

## 3. 架构与数据流

分层保持 `React/Vite -> FastAPI Router -> Service -> RAG/Core -> PostgreSQL、向量/图存储、Redis、文件工作区`。上传 API 创建任务，Worker 解析并写入索引，轮询/SSE/WS 反馈；查询按 JWT/RBAC/KB 范围检索并把会话写入 PostgreSQL。浏览器不能接收本地路径、模型目录、密钥或未授权任务事件。

PostgreSQL 是认证、共享状态、迁移历史和业务仓库的权威后端。`WORKING_DIR`、上传、输出和 ODL 产物按任务/实例隔离；缓存/WS 仍有进程内状态，横向扩展前必须补充共享协调。

## 4. 核心目录导航

| 路径 | 职责 |
|---|---|
| [`server.py`](server.py) | FastAPI 组装、生命周期、健康与指标 |
| [`raganything/routers/`](raganything/routers/) | HTTP、WebSocket、权限边界 |
| [`raganything/services/`](raganything/services/) | 业务服务、认证、KB、WS、仓库 |
| [`process_worker.py`](process_worker.py) | 文档处理 Worker 入口 |
| [`frontend/src/`](frontend/src/) | React 页面、API、SSE 客户端 |
| [`migrations/`](migrations/) | PostgreSQL 演进 |
| [`tests/`](tests/) | 后端、安全、部署和回归测试 |
| [`openspec/`](openspec/) | 主规格与 active changes |
| [`scripts/`](scripts/) | 迁移、质量检查、部署辅助 |

## 5. 业务规则

### 稳定现状

- 所有受保护接口使用 `require_permission()`；前端隐藏不能替代后端授权。
- `can_assign_role()` 限制操作者只能管理不高于自身等级的角色；最后一个超级管理员不可删除/归档。
- 用户敏感更新在同一事务锁定 actor 和 target 并读取当前持久角色；直接仓库调用也必须传 actor。
- WebSocket 握手持久化 `token_jti`；每次收发复核撤销和 session generation，失效以 `4001` 关闭。
- 普通任务事件只发给持久化 owner，payload 不含文件名、路径、KB 名或原始异常；监控通道要求 `monitor:read` 并只发聚合脱敏字段。
- Agent/会话必须绑定调用者可访问的 KB；媒体只能通过受控端点访问。
- `persist-kb-access-grants` 的运行时授权模型已被 `global-resource-visibility-retire-kb-membership` 替代：有 `kb:read` 的角色全局可见现有 KB，写入/管理/删除仍分别由全局能力与每 KB capability 投影控制；`allowed_kbs`、管理员 grant 控件和成员运行时已退役，历史表和迁移仅保留审计/回滚语义。
- 隔离查询容量优化已确认 30 VU 的非成功阶段为测试镜像固定码
  `query_core_acquire`：独立 KB 并发初始化时，query core 可能在 lease 登记前被
  LRU 淘汰；已在缓存发布、lease 登记和淘汰之间加原子顺序并补回归测试。修复后的
  10 VU 可比重测尚未完成，不能宣称容量改善或继续 40/50。
- Profile B 原 1/5/10/20 链路后，30 VU 在请求全成功、CPU/RSS 正常的情况下触发
  TTFT/总耗时门禁（P95 4658.646/5152.428 ms）；恢复采集实际健康，但运行器曾把
  查询非零退出码误报为恢复失败。该归因已在工作区修复，并将 Profile B 固定并发
  从测试专用 `MAX_ASYNC=1` 调整为 `4`，写入配置指纹并要求前序一致；新的
  1/5/10/20/30 重基线尚未在远端完成，40/50 不得启动。
- 后续修复验证完成：profiling 关闭的 10 VU 为 `212/212` 成功但仍触发原 85%
  CPU 门禁；授权诊断 20/30 VU 分别为 `967/967`、`813/813` 成功且无 SSE 错误。
  20/30 结果仅为诊断证据。一次独立的 8 vCPU/24 GiB mock direct-50 诊断为
  `638/638` 成功、无 SSE/OOM/重启/清理异常，但 TTFT/总耗时 P95 为
  `17.153/18.512s`，超过 `2.1/2.7s` 门禁；它不构成有序阶梯、真实千问或生产
  容量证据。后续须实施 provider-scoped 并发治理并用真实账号限额重验。

### 进行中

- 新上传设置采用平台/个人/KB/单次覆盖快照；历史快照不变。
- 历史文档 readiness 只读预览已实现，证据不足的记录保持原状。

## 6. 技术栈、配置与运行

- Python 3.10+、FastAPI/Uvicorn、asyncpg、Prometheus；前端 React 18、Vite 5。
- 配置来自环境变量和部署文件；摘要只记录变量名，不记录值。
- 本地后端：`.venv\\Scripts\\python.exe server.py`（API 8001）；前端 Vite 5173。
- Docker Compose 服务包含 app、postgres、redis、migrate、marker、nginx；app 只在内部网络监听，Nginx 对外提供入口。
- `/api/live` 只检查进程；`/api/ready` 检查依赖。健康检查不得把 PG 瞬断当作存活失败。
- 迁移执行前必须完成备份确认并设置 `MIGRATION_BACKUP_ACKNOWLEDGED=true`；公开演示发布已在既有可恢复备份确认后受控执行 034/035，其余迁移仍须单独审批。

## 7. 开发约束与验证

- 保留用户和并发工作区改动；提交只包含当前任务拥有文件，不夹带 `.env`、密钥或无关改动。
- 代码级证据、构建、运行 smoke、浏览器/Worker、隔离 PostgreSQL、Docker 和生产验收必须分别报告。
- 后端测试使用 `.venv\\Scripts\\python.exe`；前端使用 `npm ci --ignore-scripts` 与 `npm run build`。
- OpenSpec apply 需执行、审查、测试三方复核；archive 前同步规格与本摘要。

## 8. 已知风险与问题

- 未经 staging 演练的 Prometheus scrape/告警不能视为已接入。
- 本机若无受控 Worker fixture、浏览器或 Docker PG 故障注入，不能声称进程树、SSE 和重启行为已真实验收。
- 首次查询可能受 KB/LightRAG 冷启动影响；应单独度量，不以分页或心跳修复宣称解决。
- 迁移、历史回填、模型依赖、外部 LLM/Embedding 可达性和生产备份仍是发布门禁。

## 9. 总结更新矩阵

| 区域 | 当前事实 | 证据/边界 |
|---|---|---|
| 认证/RBAC | 目标层级锁与最后超管保护已实现 | 聚焦测试；真实五角色仍需环境 |
| WebSocket | JTI、session generation、owner 投递、监控隔离已实现 | 单测；真实双会话待验收 |
| Worker | 进程组整组回收已实现 | 构造测试；Windows 后代进程待夹具 |
| 迁移 | advisory lock、原子历史、TLS 选项已实现 | 隔离 PG 3 passed |
| 容器 | live/ready 分离、app 无宿主端口 | 静态合约；PG 抖动 Docker 待验收 |
| SSE/CORS | PATCH、accepted、heartbeat、超时、边缘无缓冲已部署 | 聚焦测试、快速发布和浏览器库存问答通过；真实模型路径待验收 |
| Readiness | 只读预览已实现 | 无写入测试；生产回填禁止 |
| Prometheus | scrape inventory、included-router 兼容 helper、锁定镜像与低资源 Compose smoke 已验证 | staging scrape/rules 与容量级完整 Compose 仍受主机门禁限制 |
| 总结质量 | 已压缩并通过检查 | 本轮收尾验证 |

## 10. 近期任务

| 日期 | 任务/change | 类型 | 结果 | 影响范围 | 验证 | 经验/风险 |
|---|---|---|---|---|---|---|
| 2026-08-21 | remove-dag-workflow | 实现/隔离 PostgreSQL 迁移验收 | 移除 DAG 页面、REST/WS、执行器、RBAC 权限、React Flow 依赖、现行规格和可变产品资料；新增 037 前向迁移，先剥离角色权限再删除运行与定义表 | Admin/WS、RBAC、前端、迁移、重置与性能脚本 | 后端聚焦 58 passed；隔离 PostgreSQL migration fresh/upgrade/repeat 5 passed；前端 220/220、Vite build、py_compile、OpenSpec strict、总结检查和 diff check 通过 | 未部署或执行生产迁移；生产 apply 前必须确认可恢复备份并遵守现有迁移确认门禁，删除的数据只能由备份恢复 |
| 2026-08-20 | persist-kb-access-grants closure | 规格收口/归档、回归与隔离 PG/浏览器验收 | 后续全局资源可见性规格已替代旧 `allowed_kbs` 持久授权和管理员 grant UI；替代规格已同步到主规格，两项 change 均以不回写旧 delta 的方式归档，未恢复已退役运行时 | KB RBAC、认证会话、管理员编辑、前端 capability gates | 后端聚焦 120 passed，前端聚焦 221 passed；一次性 pgvector 容器完成 39 个 migration fresh/verify、repeat=0、认证 API 2 passed、grant-level backfill/repeat 1 passed。干净 detached 候选 `36c2dda` 的 revision-labeled 镜像经隔离 Vite/PG/App/Nginx 以真实浏览器完成五角色列表、详情深链、读写删除控件和用户编辑无 `allowed_kbs` 验收；受影响主规格 strict 通过 | 既有数据库 checksum drift 未被写入或修复；本 change 的 Worker 和生产验收仍未执行，不可据此宣称生产发布或 Worker E2E。临时容器、卷、网络和浏览器页面已清理 |
| 2026-08-20 | video-semantic-segment-index | 验收能力实现 | 新增隔离真实 MP4 -> App 子进程 Worker -> PostgreSQL -> SSE 验收驱动；任务 5.2/5.3 未勾选 | 临时 Compose、视频 mock、HTTP/PG/SSE 契约 | 新契约测试 2 passed、编译、OpenSpec strict、diff check；未运行实际 MP4 | 必须在干净 detached、带 revision label 的镜像上提供 `--video-fixture` 后运行；mock 只证明管线，不证明外部模型语义。 |
| 2026-08-20 | production-readiness-and-durable-ingestion | 隔离预生产验收 | 完整受控 Compose 通过，OpenSpec 4.2/5.2 已完成 | 临时 pgvector、Redis、mock provider、App、Worker、Nginx | 候选 `f8af072` revision label；live/ready/health、迁移四阶段、五角色矩阵、TXT Worker 终态、PG text/vector 严格计数、retrieval-health、认证回答引用及标签清理均通过 | 仅 mock provider 与临时资源；外部模型、视频、浏览器、生产审批仍未验收，不可作为发布或生产数据变更证据。 |
| 2026-08-19 | run-isolated-cloud-capacity-benchmark | 云端隔离容量测量 | 50 个独立用户/Kb/Agent 的 retrieval-ready 门禁通过；查询 5 并发完整通过，10 并发连续 CPU 超阈停止；文本上传单任务/3 并发通过，PDF 因离线 Docling 模型缺失失败 | 临时 mock Compose、pgvector、Redis、Marker、Nginx、临时卷 | perf 工具 23 passed、编译与 diff 检查；1 用户冷/热各 55/55，5 并发 5184/5184、TTFT P95 409ms、总耗时 P95 991ms；10 并发 773/773 后 app CPU 连续 89.28/95.42/92.06% 触发停止；120 个恢复样本与生产只读探针健康 | 结论仅适用于 2 CPU/3GiB app、mock 模型和隔离容量模式；不继续 20/35/50、PDF 并发或 soak。PDF 解析会在无预置模型时尝试外网，必须由受控离线基础镜像补齐，报告见 `outputs/isolated-cloud-perf/cloud-capacity-20260819.md` |
| 2026-08-18 | media delivery release | 发布/生产只读验收 | 候选 `19b0e1fd75f15c65265f727fd651568f8e02f2b6` 已通过 fast-release 部署；图片走受控授权，表格不再显示媒体失败占位 | 生产 App/Nginx | App/Nginx 候选镜像摘要与 manifest 一致；直连与代理 `/api/live`、`/api/ready` 均 200；App/Nginx restart=0，App Docker health=healthy | PDF_PARSER 未启用且无活动生产 Worker；本轮不重处理历史文档，不能将健康检查扩展为生产 Worker 或五角色重验 |
| 2026-08-18 | isolated media acceptance rerun | Docker/Worker/五角色/浏览器 | 镜像源认证修复后，独立 PGVector/Redis/staging 目录启动；受控 tiny PDF 完成解析、多模态与图谱，重启后图片仍可授权，表格不再显示媒体失败占位 | 临时 staging 根目录（验收后移至系统 Temp 清理目录）、scratch-media-iso3、五角色、Nginx 18081 | Docker mirrors=[]；live/ready 200；DTO 4 chunks=`available 1/not_applicable 3/unavailable 0` 且无本地路径；media 200 image/png、错误 KB 404；五角色登录/读媒体 200、student 建 KB 403；真实浏览器列表/详情 Blob `naturalWidth=223`、表格正文可见；聚焦 pytest 30 passed、frontend build、strict passed；候选随后已受控发布 | Worker 任务最终 readiness gate 为 `retry_wait: retrieval_store_unavailable (vectors=0)`，文档/切块已写入但不宣称完整检索就绪；应用日志显示 pgvector 不可用并回退 NanoVectorDB。容器、网络和项目卷已清理，临时目录可人工删除 |
| 2026-08-18 | add-opendataloader-pdf-parser 7.6a | 实现 | 切块媒体状态与受控历史媒体交付完成；表格/公式无独立资产不再显示失败占位 | chunk DTO、ODL/legacy 媒体端点、切块列表与详情 | 8 个后端定向 passed、前端 218 单测 passed、build、py_compile、strict | 未批量重处理历史文档；真实浏览器文档、Worker、五角色与生产验收未执行。两项合并后端基线失败由并发 PG/RBAC 与会话 fixture 引起，不是媒体断言失败 |
| 2026-08-18 | add-isolated-performance-benchmarking | 实现/受限环境验收 | 独立 query-only Compose 用 mock 跑通正常 SSE；1 并发 10/10、5 并发 30/30 成功；已输出脱敏报告 | tests/perf、scripts/perf、隔离远端 app/PG/Redis/mock、outputs | mock SSE 16 token/done、5 并发 P95 0.691s、约8.75 req/s、60s 资源恢复采样；现有业务容器未重启 | 单身份、无 Nginx/Marker/真实模型；metrics 因当前镜像兼容性关闭；上传夹具遇重复文档完整性门禁，不构成上传验收；根盘约13.5GiB 空闲，完整压测待新增 >=87GiB 磁盘 |
| 2026-08-18 | fix-perf-metrics-router-instrumentation | 实现/代码级与容器 smoke 验收 | ENABLE_METRICS 启用时兼容 FastAPI included-router 模板解析，保留默认/自定义路径、排除规则、in-progress 与 query Histogram | `raganything/runtime_metrics.py`、`server.py`、focused tests、临时 app/PG/Redis/mock Compose | 29 tests passed、py_compile、OpenSpec strict、diff check；锁定依赖容器 smoke；低资源 Compose 中 migrate、live/ready/metrics、included `/api/auth/login` 均 200，metrics 有 query Histogram 且无敏感/raw/self handler；app/PG/Redis/mock RSS 分别约250/79/6/71MiB | 以既有镜像加当前 `server.py`/helper 只读挂载运行，非容量结论；临时容器/卷/网络/凭据已清理；未访问现有 PostgreSQL、真实模型或生产，未验收 KB/SSE/Worker/Nginx/上传 |
| 2026-08-18 | extend-isolated-performance-runtime-evidence | 受限隔离运行/云端门禁、清理与 source-only 发布 | 超低资源 mock direct-query 栈单用户 SSE 10/10 成功、metrics 与文本/视觉 mock 验证；上传诊断 app OOM 中断；性能完整候选 `6829432` 保持未部署，运行 metrics 改动已拆为候选 `afe40d3` 并通过 fast-release 发布 | tests/perf、perf runner/collector、临时 app/PG/Redis/mock、云端资源/发布门禁、生产 App/Nginx | 13 perf focused passed、py_compile；source-only metrics 测试 7 passed；发布后复核 App/Nginx/Marker 无重启，直连与 Nginx live/ready 均 200，`/metrics` 200；清理后根盘约58.1GiB可用，App/Nginx/Marker restart=0、直连与代理 live/ready 均200；当前云机8vCPU、约31.3GiB可用内存且低负载，满足受限全隔离栈门槛 | 已移除经容器引用校验的过期/失败发布标签、无挂载失败容器、全部无标签无引用镜像、旧回滚镜像与发布目录、CPU runtime 临时归档/源码、APT 缓存及 2 天前日志；本轮经用户授权进一步删除非挂载、无进程占用的 `/opt/rag-anything-backups`（约14.6GiB）、25份 `/tmp` 历史发布负载包（约2.1GiB）、无标签无引用 App 镜像、未运行 IDE 版本及可再生成 Node/pnpm 缓存，回收约22.2GiB；保留当前生产工作目录、运行容器、Docker 卷、数据库、当前/立即回滚镜像与 CPU runtime。完整压测仍须先补 Linux 运行器、每VU独立凭据及 full-stack 标签/资源采样；上传仅在唯一文本 diagnostic 达到 retrieval_ready 后开始。未重建基础镜像：完整候选的门禁来自测试专用 Dockerfile/requirements，且仓库无可执行的受控 base-release 入口；CPU runtime 的生产构建验收仍待完成。未发起真实查询，query phase Histogram 尚未在生产 scrape 中物化；结果不代表检索、吞吐、容量、真实模型或生产。报告见 outputs 受限查询运行证据 |
| 2026-08-17 | harden-runtime-security-and-stream-resilience | 实现 | 18/18 tasks 完成 | RBAC/WS/Worker/迁移/SSE/部署 | 84 后端、216 前端、构建、strict | 外部 staging 仍开放 |
| 2026-08-17 | chunk pagination | 实现/验收 | 分页、筛选、浏览器流程通过 | 文档详情 | 401 chunk 隔离库 | 冷启动需另测 |
| 2026-08-17 | chunk pagination release | 发布 | fast release 健康 | App/Nginx | direct/proxy 200 | 无迁移 |
| 2026-08-17 | agent stream zero body | 修复/发布 | 首事件、会话包装与 Nginx 无缓冲转发已部署 | Agent SSE | 11 后端、21 前端、构建、健康、浏览器库存问答 | 冷启动切换窗口可短暂 502，重试后稳定 |
| 2026-08-17 | public demo controlled release | 发布/迁移 | 034/035 已应用，App/Nginx 已切换；候选 `2d26495` 修复 SSE 首事件/超时回收 | 生产 PG/App/Nginx | archive checksum、plan/verify、direct/proxy ready 200、restart 0、匿名流保持连接 | 完整回答/引用/媒体、撤销和限流待超管验收 |

## 11. 历史里程碑与资料索引

- 认证与 RBAC：`migrations/001_pg_schema.sql`、`migrations/015_restore_5level_rbac.sql`、`raganything/permissions.py`、`raganything/services/pg_auth_repo.py`。
- 运行安全 change：`openspec/changes/harden-runtime-security-and-stream-resilience/`。
- 部署与健康：`Dockerfile`、`docker-compose.yml`、`deploy/fast-release/`、`deploy/prometheus/release-scrape-inventory.yml`。
- 迁移工具：`scripts/pg_migration_runner.py`；检查器：`scripts/check_project_summary.py`。
- 产品和架构资料：`PRODUCT.md`、`DESIGN.md`、`docs/`、`outputs/`；生成物不作为代码验收证据。
- 旧 active changes 需按 `openspec status` 复核，不因勾选数直接宣称发布。

## 12. 本轮验收结论（2026-08-17）

- 已完成：隔离 PostgreSQL 迁移器集成验收（3 passed）、总结质量检查、代码级测试/构建/编译/strict/static checks。
- 已完成生产公开演示发布：从完整候选提交构建 App/Nginx，迁移器 `plan` 仅为 034/035、`verify` 为 `pending=0`；数据库表/索引存在，直连与同源 `/api/health`、`/api/ready` 均为 200，容器重启计数为 0。候选 `2d26495` 增加 SSE 即时 accepted、KB 获取心跳和非阻塞超时回收；公网匿名页请求保持连接已实测。
- 可继续但需受控夹具：Windows 父子进程终止实测、Compose 中 PG 暂停时 live/ready 与重启窗口。
- 必须由外部环境/人工操作：Prometheus staging scrape 与 Alertmanager 演练、公开演示真实回答/引用/媒体/撤销/限流验收（匿名连接保持已验证）、历史 readiness 回填、真实模型 Worker E2E。
- 本轮已完成 034/035 生产迁移和公开演示镜像发布；未执行生产回填或工作流改动。
