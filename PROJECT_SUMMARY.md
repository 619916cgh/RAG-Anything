# RAG-Anything 项目核心总结

> 本文件是项目任务的首要导航。实际代码、迁移、运行配置和 OpenSpec 规格优先于本摘要；敏感值、用户数据和运行日志不得写入。

## 0. 元信息与使用规则

| 项目 | 当前值 |
|---|---|
| 最后核验日期 | 2026-09-03（Asia/Shanghai） |
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
| 2026-09-08 | video54-provider-governance-migration-repair | 本地数据库受控迁移修复 | 确认本地 raganything 数据库缺少 036_provider_governance.sql 的三张 Provider Governor 表；先完成 PostgreSQL custom backup 并通过归档可读性检查，再在保持 LF 的临时迁移副本中仅应用 036；未执行不可逆的 037_remove_dag_workflow.sql | 仅本机 PostgreSQL schema；无源码、生产资源或视频测试代码修改 | 备份 SHA-256 已记录于本轮脱敏交接；官方 runner plan/verify 仅报告 036 pending，apply --backup-acknowledged 成功；provider_call_leases、provider_waiters、provider_circuit_state、video_assets、video_segments 均存在，036 history=applied | 解决共享 Worker 前置缺表问题；仍需重新上传/重跑 Video 5.4 才能取得新的 Worker/浏览器证据；037 需单独审阅和批准，不能把本地迁移修复视为生产验收 |
| 2026-09-04 | video54-upload-task-diagnosis | 单次隔离 Browser 上传诊断 | mock run 中 `/api/upload/batch`=200；唯一任务由 Worker 消费，约 10 秒从 processing 到 completed，progress=100、retry=0、failure stage=none。此前 `not_ready` 确认为 harness 合成值，不是产品终态。任务归属的 document/segment 观测未关联到目标任务，故 target readiness 与 segment 数仍为未观测，不能归因视频分段或 Provider 失败 | run-owned Compose、Browser、mock provider；仅一个 KB/上传任务，已清理 | 脱敏 evidence `C:\Users\98014\AppData\Local\Temp\video54-upload-diagnosis-run-20260904-003\browser-stage-evidence.json`；cleanup/foreign inventory passed | 不执行 Agent/thread/query、SSE、Phase A/B 或五角色；不构成完整 Video 5.4 或生产验收。后续仅可补 task-to-document 观测映射后重新授权诊断 |
| 2026-09-02 | video54-browser-setup-navigation-observability | 隔离 Browser setup-only 诊断 | 两次 run-owned mock Compose setup/navigation 均到达目标 Agent；本轮复跑主文档/目标导航均 200，最终 `/agents/:agent`，console/page error=0；记录两个 `net::ERR_ABORTED` 请求 | 临时 acceptance Compose、PostgreSQL、Redis、mock provider、Browser；资源已清理 | 复跑证据 `C:\Users\98014\AppData\Local\Temp\video54-setup-rerun-20260902-174510-16e457846d\browser-stage-evidence.json`；主工作区无临时改动 | 仅证明 setup/navigation 在 mock 隔离环境通过；未执行 SSE、persisted、Phase B、五角色、完整 Video 5.4 或生产操作 |
| 2026-09-03 | video54-browser-phase-a-formal | 隔离正式 Phase A | failed：qualified image identity 后，mock run 停在 `browser-desktop-super_admin-new-video-citation-render`；`persisted_citation=0`，assistant/citation/player DOM、visibility、reload、media、Range 均 `not_reached`，Phase A 不通过 | run-owned Compose、PostgreSQL、Redis、mock provider、Browser；已清理 | schema 4 browser evidence `C:\Users\98014\AppData\Local\Temp\video54-phasea-formal-20260903-0400\browser-stage-evidence.json`；SSE/persisted conversation/assistant 已通过；aggregate runner evidence 仍 schema 2，runner output 保留但无 service log artifact | image preflight 已 qualified，但不等同 Phase A；未执行 Phase B、五角色、完整 5.4、生产或真实 Provider |
| 2026-09-03 | video54-phase-a-batch-ui | 修复并一次正式 Phase A 重跑 | harness `d2d3593` 将 upload-progress 限定到 `#server-upload-tasks` 的 exact filename 任务行并加入脱敏 locator 诊断；`/api/upload/batch`=200、locator 唯一匹配，随后在 `browser-desktop-super_admin-video-upload-terminal` 后资源契约停止：task final/retrieval/SSE/persisted citation 未通过/未到达；结论 INCONCLUSIVE，未重试 | run-owned Compose/Browser；无产品代码改动；cleanup passed，foreign Docker unchanged | evidence `C:\Users\98014\AppData\Local\Temp\video54-phasea-locator-formal-20260903-1840\browser-stage-evidence.json`；`evidence.json`、runner/browser output、service logs、owner manifests 同目录 | 不构成 Phase B、完整 Video 5.4、真实 Provider 或生产验收 |
| 2026-08-26 | windows-storage-cleanup | 主机 C/D 存储释放 | C：关闭休眠、DISM；分页迁移未生效后回退 Windows 自动管理。D：备份 metadata 后删除基包+3 个 failed Stage 包；精确删除 102 个未引用历史 RAG 镜像，清理两阶段未使用 BuildKit cache | Windows C/D、Docker/Temp；Codex 保持 C 原位 | C 可用约 2.64 GiB -> 19.4 GiB；D 可用约 261.2 GiB -> 274.6 GiB；candidate/rollback/pgvector、11 容器、custom networks、volumes identity 无漂移；VHDX compact 被系统取消，未完成 | 未清 C 缓存/旧 worktree；v2/v3 包保留；Docker default bridge 重启后正常重建；未访问云端/生产，无源码改动 |
| 2026-08-27 | stage3-production-readiness | v3 supply-chain 最终收口 | v3 83-file immutable bundle 的六份 Candidate/Rollback digest-bound SBOM/license/vulnerability evidence 完整通过；资格为 `offline-release-qualified` | v3 verifier/evidence、OpenSpec、handoff、总结 | read-only verifier、51 focused tests、py_compile、Node syntax、locked frontend build、无 runtime Compose render、strict、diff、summary check | 仅本地离线资格；Docker 未启动、11 个共享容器未触碰、run-owned scanner/DB/raw output 已清理；未访问云端或生产资源，未执行生产操作 |
| 2026-08-26 | stage3-production-readiness | 完整隔离 rehearsal 收口 | candidate `9798feddb37a9e8ade6ffdda9306df7ff33d8361` 与 rollback `36c2ddaa01b5a2025d6d44980e174d1c2023be10` 通过 revision/platform/digest/import 核验；同一 Run 完成 inventory、backup/restore、Compose、迁移、Worker/TXT/Markdown/retrieval、duplicate、恢复、SSE/citation、五级 RBAC、并发 1/3/5、recovery sampling、browser desktop/mobile、observability、rollback | run `stage3-9798fed-b31c46f3de5f8926`、run-owned PostgreSQL/Compose/backup | evidence `C:\Users\98014\AppData\Local\Temp\stage3-9798fed-run\formal\stage3-evidence.json`；补充 network/daemon retry cap 后全链通过，repair budget 使用 0；cleanup passed，foreign Docker 资源未触碰 | OpenSpec 4.1 已完成；未执行生产部署、生产迁移或生产数据操作，外部真实 provider 仍 deferred |
| 2026-08-26 | stage3 offline release bundle | 离线发布包/恢复演练收口 | 生成 run-owned 不可变包，记录 candidate/rollback ancestry、OCI identity、镜像/Git/migration/script checksum、名称级 secrets、host 前置与新服务器 runbook；包内 app archive 与已通过离线 import → candidate health → rollback health 演练的 archive checksum 一致 | `scripts/stage3_offline_release_bundle.py`、离线 tar、OpenSpec handoff、`D:\stage3-offline-release-bundle-20260826` | 聚焦离线包/Stage3 tests 25 passed、py_compile、checksum verify；本轮新增 D: Compose probe 失败后仅清理其 own resources，foreign Docker inventory 未变 | 未访问云端、生产配置/数据库/数据；D: 包不等同新服务器发布，仍须备份、status/plan/verify、审批和 live/ready/Worker/监控/合成验收 |
| 2026-08-25 | update-rag-introduction-docx | 文档事实核对/排版保留 | 基于当前源码、规格和项目总结更新 Downloads 中的 RAG 多模态知识库介绍 DOCX；仅替换原 1x2 表格右单元格正文文本，保留页面、表格、样式和未变化内容；另生成逐段差异清单 | 产品介绍、解析器、视频/检索、KB 生命周期、RBAC、部署、模型 profile、智能体模板 | 61 段文字差异；更新包 document.xml 非文本结构归一化一致，A4/页边距/列宽/89 段正文保持；LibreOffice 直接渲染 4 页并完成四页视觉检查；技能验证器因本机 GBK 解码报错，已用 XML well-formed、包结构和渲染结果补充验证 | DOCX 原文件未覆盖；文档不宣称未完成的真实 Worker、视频、外部模型、浏览器或生产验收；后续若功能事实变化需重新核对介绍文档 |
| 2026-08-20 | fix-duplicate-upload-task-provenance | 实现/代码级回归 | LightRAG 插入链路持久化上传 `track_id`；终态解析、Worker 本地检查、异常回写和标签恢复均按任务归属隔离。当前任务 duplicate 占位只在原始文档已 `processed` 时复用其 retrieval/tag target；标签恢复可从当前 duplicate 反查 canonical 文档 | 重复上传、retrieval readiness、自动标签 | 上传任务归属 7 passed、标签恢复 2 passed、Worker 3 passed、相关模块编译通过；完整相关三文件为 120 passed、7 个并发 identity/RBAC/mock 失败，详见本轮记录 | 未在隔离 PostgreSQL/App/Worker 或云端执行真实重复 DOCX；未部署、未重试或修改线上任务，生产验收仍待受控发布后执行 |
| 2026-08-20 | persist-kb-access-grants closure | 规格收口/归档、回归与隔离 PG/浏览器验收 | 后续全局资源可见性规格已替代旧 `allowed_kbs` 持久授权和管理员 grant UI；替代规格已同步到主规格，两项 change 均以不回写旧 delta 的方式归档，未恢复已退役运行时 | KB RBAC、认证会话、管理员编辑、前端 capability gates | 后端聚焦 120 passed，前端聚焦 221 passed；一次性 pgvector 容器完成 39 个 migration fresh/verify、repeat=0、认证 API 2 passed、grant-level backfill/repeat 1 passed。干净 detached 候选 `36c2dda` 的 revision-labeled 镜像经隔离 Vite/PG/App/Nginx 以真实浏览器完成五角色列表、详情深链、读写删除控件和用户编辑无 `allowed_kbs` 验收；受影响主规格 strict 通过 | 既有数据库 checksum drift 未被写入或修复；本 change 的 Worker 和生产验收仍未执行，不可据此宣称生产发布或 Worker E2E。临时容器、卷、网络和浏览器页面已清理 |
| 2026-08-20 | govern-qwen-provider-concurrency | 本地实现/隔离真实 Qwen 阶梯 | 新增 036 provider 租约/等待者/熔断迁移、PostgreSQL Governor adapter、Qwen LLM/VLM/contextual/Agent/RAG/rerank/embedding/autorepair/上传回退入口包裹、优先级、首字前有界重试、可恢复半开探针、固定状态熔断指标、私有 RPM/TPM 完整性验证、Qwen runner 及容量专用候选镜像；真实 Qwen 10/20/30 阶段通过，40 阶段因 TTFT P95 门禁硬停止 | provider-governance、模型构造、查询入口、用户设置、Agent SSE、manifest-owned Profile B Qwen mode | 10: 183/183，TTFT/总耗时 P95 1514/5428ms；20: 395/395，1627/5386ms；30: 513/513，2041/5953ms；40: 545/545，5309/8782ms；四阶段均恢复 120/120、自动清理、生产探针健康，生产 App/Nginx restart=0；本地聚焦 50 passed、py_compile、diff check | 40 阶段为 TTFT 性能门禁失败；无 429、超时、重试、资源或数据库健康异常，但现有脱敏报告不足以区分应用排队与上游首字延迟。按规则未执行 50，不得宣称 50 VU 或生产容量通过；补齐分段延迟证据后优化并从 10 重跑。|
| 2026-08-21 | govern-qwen-provider-concurrency | runner 归因与 Worker readiness 诊断修复 | 增加 accepted/agent_info/retrieval/first-chunk/done 固定事件边界；修复 Qwen readiness 诊断对 `create_rag` 传入不存在参数而必然失败的问题，现以冻结文本上传快照、实时 catalog 指纹、LightRAG 初始化和 governed embedding preflight 进行脱敏分类 | Profile B runner、Worker RAG 初始化、真实 Qwen 归因 | 一次修复后真实 Qwen 10 VU 在 readiness 硬停止：Governor lease、embedding 与 chat smoke 均通过，`create_rag_smoke=rag_init_error`；随后诊断改为真实 `docling` 快照并细分构造、解析器、LightRAG 和 PG 存储标签。本地 `tests/perf/test_perf_tool_units.py` 与 `test_qwen_runner_contract.py` 51 passed、脚本 py_compile、diff check | 不得进入 20 VU。重跑一次新 10 VU 诊断以区分候选镜像解析器依赖、LightRAG 初始化或 PG 存储；此前 reports 不可作为容量通过，50 VU/生产容量仍未通过 |
| 2026-08-21 | remove-dag-workflow | 实现/隔离 PostgreSQL 迁移验收 | 移除 DAG 页面、REST/WS、执行器、RBAC 权限、React Flow 依赖、现行规格和可变产品资料；新增 037 前向迁移，先剥离角色权限再删除运行与定义表 | Admin/WS、RBAC、前端、迁移、重置与性能脚本 | 后端聚焦 58 passed；隔离 PostgreSQL migration fresh/upgrade/repeat 5 passed；前端 220/220、Vite build、py_compile、OpenSpec strict、总结检查和 diff check 通过 | 未部署或执行生产迁移；生产 apply 前必须确认可恢复备份并遵守现有迁移确认门禁，删除的数据只能由备份恢复 |
| 2026-08-26 | security-claim-audit | 事实核验 | PG/JWT/五级 RBAC/审计/撤销、CORS、限流和请求体限制有实现；上传 API 未统一扩展名白名单，对外错误非全局脱敏 | 认证、网络、上传、权限 | auth+release security 39 passed；upload surface+KB regression 23 passed；RBAC 3 failures | 不得把上传白名单、全局错误脱敏或持续生产扫描写成已完成；生产/Worker/provider/browser 仍按既有门禁。 |

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
