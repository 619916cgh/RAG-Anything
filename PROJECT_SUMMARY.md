# RAG-Anything 项目核心总结

> 本文件是项目任务的首要导航。实际代码、迁移、运行配置和 OpenSpec 规格优先于本摘要；敏感值、用户数据和运行日志不得写入。

## 0. 元信息与使用规则

| 项目 | 当前值 |
|---|---|
| 最后核验日期 | 2026-09-09（Asia/Shanghai） |
| 核验分支 | `codex/paginate-large-kb-document-summaries` |
| 基准提交 | Stage 3 离线资格 `f751e54f2e57`；治理 checkpoint `05efa8c5d8c7` |
| 工作区状态 | 2026-08-27 协调者收口时干净；新并行任务以实时 `git status` 为准 |
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
- `stage3-production-readiness` 已新增固定非生产编排器：仅接受 clean detached SHA、本地 Docker、临时工作目录、隔离数据库与 image revision/digest；固定 inventory、backup/restore、既有 Compose acceptance、rollback identity 和清理阶段，有限重试并递归脱敏 evidence。聚焦测试 50 passed、编译、strict 与 diff check 通过。一次实际预检使用 detached `f8af072` candidate 在 image-identity hard stop 停止：没有不同且可验证的 rollback image；未创建本轮 Compose/backup/restore 资源，evidence=`not-releasable`，修复预算使用 0。完整 Stage 3 rehearsal 仍待两个不同、revision-labelled disposable image 和 verified disposable backup bundle；生产/真实 provider/browser 仍未授权或验收。
- Stage 3 完整隔离 rehearsal 已在 clean detached candidate `9798feddb37a9e8ade6ffdda9306df7ff33d8361` 上通过；rollback 基线为有独立隔离验收记录的 `36c2ddaa01b5a2025d6d44980e174d1c2023be10`。两镜像均为 `linux/amd64`、OCI revision/digest 匹配且 import smoke 通过。Run `stage3-9798fed-b31c46f3de5f8926` 的 inventory、run-owned backup/restore、Compose 启动/health、迁移 fresh/upgrade/repeat/intentional-failure、TXT/Markdown/retrieval、duplicate、App/Worker recovery、SSE/citation、五级 RBAC、concurrency 1/3/5、recovery sampling、browser desktop/mobile、observability、video worker 与 rollback 均通过；repair budget 使用 0。外层及 acceptance cleanup 通过，run-owned PostgreSQL/网络/卷/容器已清理，foreign Docker resources untouched；脱敏 evidence 为 `C:\Users\98014\AppData\Local\Temp\stage3-9798fed-run\formal\stage3-evidence.json`。OpenSpec 4.1 已完成；未执行生产部署、生产迁移或生产数据操作，外部真实 provider 仍 deferred。
- 原 Stage 3 离线包 `D:\stage3-offline-release-bundle-20260826` 是 immutable 73-file `not-qualified` 证据：旧 rehearsal 以纯十六进制 bootstrap password 被 App 策略拒绝；迁移/PG/Redis/mock 通过，原包及 archive 从未改写，foreign Docker 未触碰。
- Stage 3 v2 `D:\stage3-offline-release-bundle-20260826-v2` 不可变，五 archive 未改写；v3 `D:\stage3-offline-release-bundle-20260826-v3` 的 `SHA256SUMS` 根摘要为 `46b8d55394e3b25c2706677b1cfc584162ac554a1839be98c484dcedef416912`，82 个 payload 加 manifest 共 83 文件。candidate `9798feddb37a9e8ade6ffdda9306df7ff33d8361` / rollback `36c2ddaa01b5a2025d6d44980e174d1c2023be10` 均为 revision-matched `linux/amd64` OCI；六份 digest-bound SBOM/license/vulnerability evidence 通过 Syft `1.51.0`、Grype `0.117.0` 与 current/valid DB `v6.1.9`（更新时间 `2026-08-25T00:19:07Z`）验证。verifier、focused tests、编译、locked frontend build、无 runtime Compose render、strict、diff 和总结检查通过后，v3 为 `offline-release-qualified`；仅代表本地离线发布资格，不代表 production-deployed、production-accepted 或真实生产 Provider 验收。Docker 未启动、11 个共享容器未触碰，run-owned scanner/DB/raw output 已清理；未访问云端或生产资源。
- `govern-qwen-provider-concurrency` 的 orphaned 本地实现已由协调者收口为代码/模拟 checkpoint：Provider Governor、036 schema/manifest、主要 Qwen LLM/VLM/RAG/Agent/rerank/embedding/上传入口、有限重试、优先级、熔断与脱敏指标/runner 接线已入库；2026-08-27 增补 half-open probe owner fencing，避免过期 probe 覆盖新实例。专用合同/性能工具测试 100 passed、`py_compile`、strict 与 diff check 通过。OpenSpec 仍为 18/30：真实 disposable PostgreSQL/多实例、完整入口和重试边界、usage accounting/完整 metrics、真实 Qwen 10→50 阶梯与恢复分类未完成；不据此提升限额、部署或宣称生产/容量通过。
- 2026-08-21 Qwen readiness 诊断继续修复：Worker 现在检查 `_ensure_lightrag_initialized()` 的结构化返回值，失败时在模型预检和文档写入前以固定初始化错误退出；容量 runner 保留 `model_preflight`、`finalize`、`quota` 等受控失败阶段并扩展脱敏聚合。相关 Worker/性能测试 72 passed，脚本编译、总结检查和 diff check 通过；远端候选镜像尚未重建，真实 Qwen 10 VU 仍需在上传修复后的候选后重跑。
- 2026-08-22 真实 Qwen 严格阶梯已完成并按门禁停止：10/20/30/40 阶段分别为 186/186、375/375、540/540、540/540 成功，TTFT P95 为 1459/1621/1944/4994ms，完整回答 P95 为 5575/5368/5718/8618ms；每阶段均 120/120 恢复样本、生产探针健康、无重试/协议错误/资源停止、清理 verified。50 阶段 520/520 请求成功且恢复/资源/清理均正常，但 TTFT P95=10002ms 超过 5000ms 门禁，分类为 `profile_b_hard_stop`，按规则停止。50 的 `accepted_to_first_chunk` P95=9859ms，而 `first_chunk_to_done` P95=4449ms；无 429、超时或重试，现有脱敏报告没有 Provider 排队计数，因此只能将其归为应用侧/上游首字前延迟待归因，不能宣称 50 VU 通过或生产容量通过。

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
- 多轮 AgentChat 以 `thread_id` 关联 PostgreSQL `agent_conversations`/`agent_messages`；当前请求实际注入最近消息（默认 10 轮、约 2000 token），已持久化摘要会由 RAG/ReAct/CoT 读取并注入 Prompt，摘要默认消息数超过 20 条后触发；前端不提交历史数组，刷新后默认选首个会话。
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
- 外部 Docker Desktop 反馈（#625）：Windows/WSL2 下 AF_UNIX stale-socket 重命名失败（WinError 1920）可能导致 `desktop-linux` pipe 缺失；与本机现象同类但未证实同因，不能归因 Video 5.4。不得据此重置 Docker 或删除 WSL/VHDX。
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

前端遮罩修复完成：弹窗；单测/Vite/diff passed，未执行浏览器/Worker/生产验收。

| 日期 | 任务/change | 类型 | 结果 | 影响范围 | 验证 | 经验/风险 |
|---|---|---|---|---|---|---|
| 2026-09-10 | KB capability helper return regression | 修复/回归 | 恢复编辑 capability helper 的返回值，避免 `/api/kb/list` 和编辑权限检查读取 `None` | KB 列表与编辑权限投影；无数据库、迁移或 RBAC 规则变化 | 五角色 capability、KB 列表聚焦测试与编译检查 | 语法编译无法发现缺失业务返回值；媒体交付改动需覆盖共享 KB capability 回归 |
| 2026-09-10 | new-upload-media-delivery-v2 | 实现/生命周期与身份修复 | 修复 finalize 后访问已关闭 LightRAG DB，以及纯视频预注册未写 upload task identity 导致 v2 审计在 99% 失败；Worker 使用共享 PG 事务审计，纯多模态 doc status 从创建起写入并保留顶层 `track_id` 与 `metadata.task_id`，冲突失败关闭 | Worker、文档状态、媒体契约、上传错误映射 | 原修复后端 151 passed/1 skipped、前端 234 passed、Vite build；本轮相关后端 60 passed、compile、两个相关 OpenSpec strict、summary/diff 通过 | 不回填旧任务；全仓 OpenSpec strict 仍有历史失败；真实视频重传、Range 206 与浏览器定位尚未验收，不构成 5.4 或生产验收 |
| 2026-09-10 | video54-migration-only-r2 | 独立 migration-only Run | 固定候选 a030e8d19a102f7aa94ee05ae54b72bcfe6f1393 通过 detached/clean、唯一数据库 identity binding、PSQL 16.3 与 Docker desktop-linux preflight；官方 scripts/pg_migration_runner.py 在首个数据库命令以脱敏 psql-exit-2 失败后停止，未进入 upload/task/Worker/Browser；cleanup passed，foreign inventory unchanged | 仅 run-owned disposable PostgreSQL、命名卷与脱敏 evidence；无产品源码、历史 migration SQL、当前数据库或生产资源改动 | 新 Run identity；fresh isolated PostgreSQL；migration failed at migration-sql，history not reached，return_code=2；Docker inventory 2/15/14 前后不变 | not-releasable；未重试；不得将本轮结果视为迁移成功、Worker、浏览器、完整 Video 5.4 或生产验收 |
| 2026-09-09 | video54-provenance-bounded-runner | 独立 provenance 有界运行 | 候选 `5477a0f558bcbac5639a13cdc4ce9c3a92d4f6d7` 在 clean detached checkout 通过 preflight；视频仅以脱敏大小与 SHA-256 复制到 run-owned 输入，官方隔离 PostgreSQL 迁移失败后立即停止；upload、task、Worker/document persistence、serializer、mapping 均未到达，未执行 Browser/SSE/Phase A/B/retrieval/video-segments/真实 Provider/生产部署 | 仅 run-owned 临时目录与隔离迁移尝试；无源码、当前数据库或生产资源改动 | evidence：`C:\Users\98014\AppData\Local\Temp\provenance-bounded-run-20260909\evidence.json`；preflight passed，migration failed，cleanup passed；foreign Docker 计数 `2/15/14` 前后不变；输入副本已清理 | `not-releasable`；迁移失败原因按 runner 脱敏为 `migration-runner-failed`，未重试；不得将本轮结果视为 Worker、浏览器、完整 Video 5.4 或生产验收 |
| 2026-09-09 | conversation-summary-threshold-and-injection | 实现/回归 | 摘要默认触发轮数 3→10；普通 RAG/ReAct/CoT 从线程读取已持久化摘要并注入 Prompt，摘要为空/关闭时仍用近期历史；无迁移/API 变更 | 后端 Agent 上下文、配置示例、OpenSpec 规格 | 定向 62 passed、py_compile、OpenSpec strict、diff check 通过 | 未执行真实模型、浏览器或生产验收；近期历史与摘要重叠为既定最小改动 |
| 2026-09-09 | complete-citation-provenance | 实现/隔离 PG/本地 038 修复 | 新增 038 citation_provenance 与 citations 持久化；ODL/文本/图片/视频 provenance、统一 citation DTO、Agent/AutoRepair/Public Demo、前端展示与生命周期 fail-closed 已实现；本地 raganything 已备份并应用 038 | 迁移、解析、查询、Agent、Demo、前端、删除清理 | 后端相关聚焦 221 passed、前端 233 passed、Vite build、OpenSpec strict、diff/compile；隔离 PG fresh/upgrade/repeat/failure/recovery 5 passed，并发/跨 KB 隔离通过；本地 custom backup 已核验 | 仅本地库应用 038，生产仍未；Worker+浏览器链路仍需用新上传 PDF、图片、视频在同 Run 验收，不能以单测/构建/隔离 PG 升级证据 |
| 2026-09-08 | video54-provider-governance-migration-repair | 本地数据库受控迁移修复 | 确认本地 raganything 数据库缺少 036_provider_governance.sql 的三张 Provider Governor 表；先完成 PostgreSQL custom backup 并通过归档可读性检查，再在保持 LF 的临时迁移副本中仅应用 036；未执行不可逆的 037_remove_dag_workflow.sql | 仅本机 PostgreSQL schema；无源码、生产资源或视频测试代码修改 | 备份 SHA-256 已记录于本轮脱敏交接；官方 runner plan/verify 仅报告 036 pending，apply --backup-acknowledged 成功；provider_call_leases、provider_waiters、provider_circuit_state、video_assets、video_segments 均存在，036 history=applied | 解决共享 Worker 前置缺表问题；仍需重新上传/重跑 Video 5.4 才能取得新的 Worker/浏览器证据；037 需单独审阅和批准，不能把本地迁移修复视为生产验收 |
| 2026-09-08 | cloudflare-deployment-boundary | 只读部署核验 | 确认 Cloudflare Pages 可承载 `frontend/dist`，但当前完整应用仍需独立 Docker/Linux 运行 FastAPI、PostgreSQL、Redis、Marker/解析 Worker 与持久化存储；未发现 Wrangler/Workers 配置，未执行云端部署 | 仅部署建议；无产品代码或云资源修改 | 静态核对 `frontend/package.json`、`frontend/vite.config.js`、`docker-compose.yml`、`Dockerfile`、`nginx.conf`、`deploy/volcano-engine-docker.md`；未访问云端资源 | 前端 API 固定同源 `/api`，Pages 单独部署必须配 Worker/Pages Functions 反代或改 API 基址；不可将 Pages/Workers 单独部署结果当作完整生产验收 |
| 2026-09-04 | implemented-function-parameter-report | 文档交付 | 生成已实现功能参数报告；字体版 13 页，保持原文件不覆盖 | 仅新增报告与脚本 | OOXML 字体审计 2194 runs、mismatches=0；完成渲染检查 | 不宣称 Provider、视频、生产或 50 VU 通过 |
| 2026-09-08 | video54-upload-task-provenance-audit | 严格单上传 provenance audit | clean detached `17b245af2e27db3221ada061854ca02b35cf14de`；run-owned Compose/临时 PG 由官方 runner fresh 初始化，1 KB/1 Browser upload/1 task，无 Agent/thread/query/SSE/Phase A/B；task=`completed`、progress=100、worker_consumed=true、retry=0、failure=`none`、timeline=6；document_id/full_id 缺失，uploaded_files/document provenance 未命中；mapping=`unmatched`、source=`document.provenance`、reason=`task_provenance_not_found`、diagnosis=`incomplete`，未请求 segments，runner=`not-releasable` | 只读审计；未改产品/当前 DB，未执行生产迁移/回填/数据操作 | artifacts：`C:\Users\98014\AppData\Local\Temp\video54-upload-task-provenance-audit-run-20260908-strict-111731`；foreign Docker 2/15/12 前后不变，run-owned resources/profile/fixture 已清理；Node、42 migration/provider/runner tests、5 video tests skipped、py_compile、diff、summary passed | 不构成 Phase A、Phase B、完整 Video 5.4、真实 Provider 或生产验收；仅证明单上传终态与 provenance 未命中 |
| 2026-09-03 | video54-browser-phase-a-formal | 隔离正式 Phase A | failed：qualified image identity 后，mock run 停在 `browser-desktop-super_admin-new-video-citation-render`；`persisted_citation=0`，assistant/citation/player DOM、visibility、reload、media、Range 均 `not_reached`，Phase A 不通过 | run-owned Compose、PostgreSQL、Redis、mock provider、Browser；已清理 | schema 4 browser evidence `C:\Users\98014\AppData\Local\Temp\video54-phasea-formal-20260903-0400\browser-stage-evidence.json`；SSE/persisted conversation/assistant 已通过；aggregate runner evidence 仍 schema 2，runner output 保留但无 service log artifact | image preflight 已 qualified，但不等同 Phase A；未执行 Phase B、五角色、完整 5.4、生产或真实 Provider |
| 2026-09-08 | video54-upload-task-provenance-bounded | 解码修复 | `abe803e` 在 `browser-upload-diagnosis` 因 GBK 停止；`b10c1af` 使用 UTF-8+replace，17 passed；Docker 不可用 | 验收代码 | evidence：`C:/Users/98014/AppData/Local/Temp/video54-upload-task-provenance-bounded-run-20260908-abe803e` | INCONCLUSIVE/not-releasable；Phase A/5.4/生产未通过 |
| 2026-09-08 | kb-qa-citation-provenance-audit | 只读能力核验 | 通用问答溯源解析为 `[来源 文档名]`/`[来源 N]`，结构化字段主要是 `index`、`document_name`、`excerpt`、`file_path`；通用 Agent SSE 当前实际仅序列化视频片段 citation，带资料名、受控媒体和 `start_ms/end_ms`。页码、入库时间、图片所属文档等不是通用 citation；AutoRepair 专用链路另有 `page/section/ingested_at` 富化 | 仅源码/规格核验，无产品改动 | `raganything/citation_parser.py`、`raganything/query/pipeline.py`、`raganything/routers/agent.py`、`raganything/services/video_segments.py`、`frontend/src/pages/AgentChatPage.jsx`、`frontend/src/components/VideoSegmentPlayer.jsx` | 普通文本引用和图片元数据目前未在通用问答 UI 以细粒度定位展示；不可将 AutoRepair 或视频专用字段表述为全局能力 |
| 2026-09-03 | video54-phase-a-batch-ui | 修复并一次正式 Phase A 重跑 | harness `d2d3593` 将 upload-progress 限定到 `#server-upload-tasks` 的 exact filename 任务行并加入脱敏 locator 诊断；`/api/upload/batch`=200、locator 唯一匹配，随后在 `browser-desktop-super_admin-video-upload-terminal` 后资源契约停止：task final/retrieval/SSE/persisted citation 未通过/未到达；结论 INCONCLUSIVE，未重试 | run-owned Compose/Browser；无产品代码改动；cleanup passed，foreign Docker unchanged | evidence `C:\Users\98014\AppData\Local\Temp\video54-phasea-locator-formal-20260903-1840\browser-stage-evidence.json`；`evidence.json`、runner/browser output、service logs、owner manifests 同目录 | 不构成 Phase B、完整 Video 5.4、真实 Provider 或生产验收 |
| 2026-08-27 | stage3-production-readiness | v3 supply-chain 最终收口 | v3 83-file immutable bundle 的六份 Candidate/Rollback digest-bound SBOM/license/vulnerability evidence 完整通过；资格为 `offline-release-qualified` | v3 verifier/evidence、OpenSpec、handoff、总结 | read-only verifier、51 focused tests、py_compile、Node syntax、locked frontend build、无 runtime Compose render、strict、diff、summary check | 仅本地离线资格；Docker 未启动、11 个共享容器未触碰、run-owned scanner/DB/raw output 已清理；未访问云端或生产资源，未执行生产操作 |
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
