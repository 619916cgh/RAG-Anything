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
- `stage3-production-readiness` 已新增固定非生产编排器：仅接受 clean detached SHA、本地 Docker、临时工作目录、隔离数据库与 image revision/digest；固定 inventory、backup/restore、既有 Compose acceptance、rollback identity 和清理阶段，有限重试并递归脱敏 evidence。聚焦测试 50 passed、编译、strict 与 diff check 通过。一次实际预检使用 detached `f8af072` candidate 在 image-identity hard stop 停止：没有不同且可验证的 rollback image；未创建本轮 Compose/backup/restore 资源，evidence=`not-releasable`，修复预算使用 0。完整 Stage 3 rehearsal 仍待两个不同、revision-labelled disposable image 和 verified disposable backup bundle；生产/真实 provider/browser 仍未授权或验收。
- Stage 3 完整隔离 rehearsal 已在 clean detached candidate `9798feddb37a9e8ade6ffdda9306df7ff33d8361` 上通过；rollback 基线为有独立隔离验收记录的 `36c2ddaa01b5a2025d6d44980e174d1c2023be10`。两镜像均为 `linux/amd64`、OCI revision/digest 匹配且 import smoke 通过。Run `stage3-9798fed-b31c46f3de5f8926` 的 inventory、run-owned backup/restore、Compose 启动/health、迁移 fresh/upgrade/repeat/intentional-failure、TXT/Markdown/retrieval、duplicate、App/Worker recovery、SSE/citation、五级 RBAC、concurrency 1/3/5、recovery sampling、browser desktop/mobile、observability、video worker 与 rollback 均通过；repair budget 使用 0。外层及 acceptance cleanup 通过，run-owned PostgreSQL/网络/卷/容器已清理，foreign Docker resources untouched；脱敏 evidence 为 `C:\Users\98014\AppData\Local\Temp\stage3-9798fed-run\formal\stage3-evidence.json`。OpenSpec 4.1 已完成；未执行生产部署、生产迁移或生产数据操作，外部真实 provider 仍 deferred。
- Stage 3 离线发布包已生成在 run-owned `D:\stage3-offline-release-bundle-20260826`：其 SHA256SUMS 覆盖 candidate/rollback/Compose 依赖镜像归档、Git archive、迁移 SQL checksum、OCI/ancestry manifest、脚本 hash、脱敏 evidence、secret 名称清单和新服务器 runbook。两 app archive 与一次通过的 isolated import → candidate health → rollback health → owned cleanup 演练归档 checksum 一致；foreign Docker resources 未触碰。新服务器仍需完成受管备份、migration status/plan/verify、批准的 apply、live/ready/health、Worker、Prometheus/alert 和合成业务验收；本轮没有任何云端或生产操作。
- `govern-qwen-provider-concurrency` 已完成 Provider Governor 核心、036 迁移/manifest、Qwen LLM/VLM/contextual/Agent/RAG/rerank/embedding/autorepair/上传回退入口包裹、优先级队列、首字前有界重试、可恢复半开熔断探针、固定状态标签指标和 Profile B Qwen runner 扩展；私有 RPM/TPM 仅在显式完整验证配置时激活，公开 DTO 保持脱敏。百炼控制台已核实 `qwen-plus` RPM/TPM 为 30000/5000000、`text-embedding-v4` 为 1800/1200000，组合验收瓶颈记录为 1800/1200000。隔离 Linux Docker 真实 Qwen 阶梯已完成 10/20/30；40 阶段 545/545 成功但首字 P95=5309ms 超过 5000ms 门禁，按规则停止，未执行 50。生产 App/Nginx 未触碰，重启计数保持 0；OpenSpec 当前 18/30 完成。新增 runner SSE 固定事件边界 P50/P95/P99 与 Provider/Query 指标可用性计数，用于下一轮 40 VU 归因；尚未重跑真实阶梯，不能宣称性能已改善。
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
| 2026-08-26 | stage3-production-readiness | 实现/隔离预检 | 新增固定 CLI、候选/目标/镜像/恢复硬门禁、有限普通环境重试和 schema v2 脱敏证据；实际 preflight 正确在 rollback image identity 不足时停止 | `scripts/stage3_production_readiness.py`、release backup helpers、isolated acceptance、OpenSpec/运维文档 | Stage3/production-readiness/release-ops/video contract 共 50 passed，py_compile、OpenSpec strict、diff check；使用 clean detached `f8af072` 与本地 image 执行，`image_identity` hard stop、cleanup=`not-started` | 不调用 `deploy.ps1`、生产迁移、生产备份/恢复或生产数据操作；缺少不同 rollback candidate image 与 verified disposable bundle，未运行 Compose/PG/Worker 全链路；外部 provider、浏览器和生产验收继续 deferred |
| 2026-08-26 | stage3-production-readiness | 完整隔离 rehearsal（未通过） | candidate `665160126dea00c2fa540b8024cc41bc5b222dbb` 与 rollback `36c2ddaa01b5a2025d6d44980e174d1c2023be10` 均完成 revision/platform/digest/import 核验；同一 Run 通过 inventory、backup/restore、Compose health、四阶段迁移和五级 RBAC，video segment-validation 硬停止 | run `stage3-6651601-65438f41`、candidate/rollback disposable Compose、run-owned PostgreSQL、backup bundle | evidence `C:\Users\98014\AppData\Local\Temp\stage3-6651601-65438f41-evidence-final2\stage3-evidence.json`；acceptance 初始尝试+2 retries 均 compose/video failure；外层/内层 cleanup passed，foreign resources untouched | OpenSpec 4.1 未完成；rollback、并发 1/3/5、browser、observability、真实 provider 与生产边界未验收；未执行生产部署、迁移或数据操作 |
| 2026-08-26 | stage3-production-readiness | 完整隔离 rehearsal 收口 | candidate `9798feddb37a9e8ade6ffdda9306df7ff33d8361` 与 rollback `36c2ddaa01b5a2025d6d44980e174d1c2023be10` 通过 revision/platform/digest/import 核验；同一 Run 完成 inventory、backup/restore、Compose、迁移、Worker/TXT/Markdown/retrieval、duplicate、恢复、SSE/citation、五级 RBAC、并发 1/3/5、recovery sampling、browser desktop/mobile、observability、rollback | run `stage3-9798fed-b31c46f3de5f8926`、run-owned PostgreSQL/Compose/backup | evidence `C:\Users\98014\AppData\Local\Temp\stage3-9798fed-run\formal\stage3-evidence.json`；补充 network/daemon retry cap 后全链通过，repair budget 使用 0；cleanup passed，foreign Docker 资源未触碰 | OpenSpec 4.1 已完成；未执行生产部署、生产迁移或生产数据操作，外部真实 provider 仍 deferred |
| 2026-08-26 | stage3 offline release bundle | 离线发布包/恢复演练收口 | 生成 run-owned 不可变包，记录 candidate/rollback ancestry、OCI identity、镜像/Git/migration/script checksum、名称级 secrets、host 前置与新服务器 runbook；包内 app archive 与已通过离线 import → candidate health → rollback health 演练的 archive checksum 一致 | `scripts/stage3_offline_release_bundle.py`、离线 tar、OpenSpec handoff、`D:\stage3-offline-release-bundle-20260826` | 聚焦离线包/Stage3 tests 25 passed、py_compile、checksum verify；本轮新增 D: Compose probe 失败后仅清理其 own resources，foreign Docker inventory 未变 | 未访问云端、生产配置/数据库/数据；D: 包不等同新服务器发布，仍须备份、status/plan/verify、审批和 live/ready/Worker/监控/合成验收 |
| 2026-08-25 | update-rag-introduction-docx | 文档事实核对/排版保留 | 基于当前源码、规格和项目总结更新 Downloads 中的 RAG 多模态知识库介绍 DOCX；仅替换原 1x2 表格右单元格正文文本，保留页面、表格、样式和未变化内容；另生成逐段差异清单 | 产品介绍、解析器、视频/检索、KB 生命周期、RBAC、部署、模型 profile、智能体模板 | 61 段文字差异；更新包 document.xml 非文本结构归一化一致，A4/页边距/列宽/89 段正文保持；LibreOffice 直接渲染 4 页并完成四页视觉检查；技能验证器因本机 GBK 解码报错，已用 XML well-formed、包结构和渲染结果补充验证 | DOCX 原文件未覆盖；文档不宣称未完成的真实 Worker、视频、外部模型、浏览器或生产验收；后续若功能事实变化需重新核对介绍文档 |
| 2026-08-20 | fix-duplicate-upload-task-provenance | 实现/代码级回归 | LightRAG 插入链路持久化上传 `track_id`；终态解析、Worker 本地检查、异常回写和标签恢复均按任务归属隔离。当前任务 duplicate 占位只在原始文档已 `processed` 时复用其 retrieval/tag target；标签恢复可从当前 duplicate 反查 canonical 文档 | 重复上传、retrieval readiness、自动标签 | 上传任务归属 7 passed、标签恢复 2 passed、Worker 3 passed、相关模块编译通过；完整相关三文件为 120 passed、7 个并发 identity/RBAC/mock 失败，详见本轮记录 | 未在隔离 PostgreSQL/App/Worker 或云端执行真实重复 DOCX；未部署、未重试或修改线上任务，生产验收仍待受控发布后执行 |
| 2026-08-20 | persist-kb-access-grants closure | 规格收口/归档、回归与隔离 PG/浏览器验收 | 后续全局资源可见性规格已替代旧 `allowed_kbs` 持久授权和管理员 grant UI；替代规格已同步到主规格，两项 change 均以不回写旧 delta 的方式归档，未恢复已退役运行时 | KB RBAC、认证会话、管理员编辑、前端 capability gates | 后端聚焦 120 passed，前端聚焦 221 passed；一次性 pgvector 容器完成 39 个 migration fresh/verify、repeat=0、认证 API 2 passed、grant-level backfill/repeat 1 passed。干净 detached 候选 `36c2dda` 的 revision-labeled 镜像经隔离 Vite/PG/App/Nginx 以真实浏览器完成五角色列表、详情深链、读写删除控件和用户编辑无 `allowed_kbs` 验收；受影响主规格 strict 通过 | 既有数据库 checksum drift 未被写入或修复；本 change 的 Worker 和生产验收仍未执行，不可据此宣称生产发布或 Worker E2E。临时容器、卷、网络和浏览器页面已清理 |
| 2026-08-20 | govern-qwen-provider-concurrency | 本地实现/隔离真实 Qwen 阶梯 | 新增 036 provider 租约/等待者/熔断迁移、PostgreSQL Governor adapter、Qwen LLM/VLM/contextual/Agent/RAG/rerank/embedding/autorepair/上传回退入口包裹、优先级、首字前有界重试、可恢复半开探针、固定状态熔断指标、私有 RPM/TPM 完整性验证、Qwen runner 及容量专用候选镜像；真实 Qwen 10/20/30 阶段通过，40 阶段因 TTFT P95 门禁硬停止 | provider-governance、模型构造、查询入口、用户设置、Agent SSE、manifest-owned Profile B Qwen mode | 10: 183/183，TTFT/总耗时 P95 1514/5428ms；20: 395/395，1627/5386ms；30: 513/513，2041/5953ms；40: 545/545，5309/8782ms；四阶段均恢复 120/120、自动清理、生产探针健康，生产 App/Nginx restart=0；本地聚焦 50 passed、py_compile、diff check | 40 阶段为 TTFT 性能门禁失败；无 429、超时、重试、资源或数据库健康异常，但现有脱敏报告不足以区分应用排队与上游首字延迟。按规则未执行 50，不得宣称 50 VU 或生产容量通过；补齐分段延迟证据后优化并从 10 重跑。|
| 2026-08-21 | govern-qwen-provider-concurrency | runner 归因与 Worker readiness 诊断修复 | 增加 accepted/agent_info/retrieval/first-chunk/done 固定事件边界；修复 Qwen readiness 诊断对 `create_rag` 传入不存在参数而必然失败的问题，现以冻结文本上传快照、实时 catalog 指纹、LightRAG 初始化和 governed embedding preflight 进行脱敏分类 | Profile B runner、Worker RAG 初始化、真实 Qwen 归因 | 一次修复后真实 Qwen 10 VU 在 readiness 硬停止：Governor lease、embedding 与 chat smoke 均通过，`create_rag_smoke=rag_init_error`；随后诊断改为真实 `docling` 快照并细分构造、解析器、LightRAG 和 PG 存储标签。本地 `tests/perf/test_perf_tool_units.py` 与 `test_qwen_runner_contract.py` 51 passed、脚本 py_compile、diff check | 不得进入 20 VU。重跑一次新 10 VU 诊断以区分候选镜像解析器依赖、LightRAG 初始化或 PG 存储；此前 reports 不可作为容量通过，50 VU/生产容量仍未通过 |
| 2026-08-21 | remove-dag-workflow | 实现/隔离 PostgreSQL 迁移验收 | 移除 DAG 页面、REST/WS、执行器、RBAC 权限、React Flow 依赖、现行规格和可变产品资料；新增 037 前向迁移，先剥离角色权限再删除运行与定义表 | Admin/WS、RBAC、前端、迁移、重置与性能脚本 | 后端聚焦 58 passed；隔离 PostgreSQL migration fresh/upgrade/repeat 5 passed；前端 220/220、Vite build、py_compile、OpenSpec strict、总结检查和 diff check 通过 | 未部署或执行生产迁移；生产 apply 前必须确认可恢复备份并遵守现有迁移确认门禁，删除的数据只能由备份恢复 |
| 2026-08-20 | video-semantic-segment-index | 验收能力实现 | 新增隔离真实 MP4 -> App 子进程 Worker -> PostgreSQL -> SSE 验收驱动；任务 5.2/5.3 未勾选 | 临时 Compose、视频 mock、HTTP/PG/SSE 契约 | 新契约测试 2 passed、编译、OpenSpec strict、diff check；未运行实际 MP4 | 必须在干净 detached、带 revision label 的镜像上提供 `--video-fixture` 后运行；mock 只证明管线，不证明外部模型语义。 |
| 2026-08-19 | run-isolated-cloud-capacity-benchmark | 云端隔离容量测量 | 50 个独立用户/Kb/Agent 的 retrieval-ready 门禁通过；查询 5 并发完整通过，10 并发连续 CPU 超阈停止；文本上传单任务/3 并发通过，PDF 因离线 Docling 模型缺失失败 | 临时 mock Compose、pgvector、Redis、Marker、Nginx、临时卷 | perf 工具 23 passed、编译与 diff 检查；1 用户冷/热各 55/55，5 并发 5184/5184、TTFT P95 409ms、总耗时 P95 991ms；10 并发 773/773 后 app CPU 连续 89.28/95.42/92.06% 触发停止；120 个恢复样本与生产只读探针健康 | 结论仅适用于 2 CPU/3GiB app、mock 模型和隔离容量模式；不继续 20/35/50、PDF 并发或 soak。PDF 解析会在无预置模型时尝试外网，必须由受控离线基础镜像补齐，报告见 `outputs/isolated-cloud-perf/cloud-capacity-20260819.md` |
| 2026-08-18 | media delivery release | 发布/生产只读验收 | 候选 `19b0e1fd75f15c65265f727fd651568f8e02f2b6` 已通过 fast-release 部署；图片走受控授权，表格不再显示媒体失败占位 | 生产 App/Nginx | App/Nginx 候选镜像摘要与 manifest 一致；直连与代理 `/api/live`、`/api/ready` 均 200；App/Nginx restart=0，App Docker health=healthy | PDF_PARSER 未启用且无活动生产 Worker；本轮不重处理历史文档，不能将健康检查扩展为生产 Worker 或五角色重验 |
| 2026-08-18 | isolated media acceptance rerun | Docker/Worker/五角色/浏览器 | 镜像源认证修复后，独立 PGVector/Redis/staging 目录启动；受控 tiny PDF 完成解析、多模态与图谱，重启后图片仍可授权，表格不再显示媒体失败占位 | 临时 staging 根目录（验收后移至系统 Temp 清理目录）、scratch-media-iso3、五角色、Nginx 18081 | Docker mirrors=[]；live/ready 200；DTO 4 chunks=`available 1/not_applicable 3/unavailable 0` 且无本地路径；media 200 image/png、错误 KB 404；五角色登录/读媒体 200、student 建 KB 403；真实浏览器列表/详情 Blob `naturalWidth=223`、表格正文可见；聚焦 pytest 30 passed、frontend build、strict passed；候选随后已受控发布 | Worker 任务最终 readiness gate 为 `retry_wait: retrieval_store_unavailable (vectors=0)`，文档/切块已写入但不宣称完整检索就绪；应用日志显示 pgvector 不可用并回退 NanoVectorDB。容器、网络和项目卷已清理，临时目录可人工删除 |
| 2026-08-18 | fix-perf-metrics-router-instrumentation | 实现/代码级与容器 smoke 验收 | ENABLE_METRICS 启用时兼容 FastAPI included-router 模板解析，保留默认/自定义路径、排除规则、in-progress 与 query Histogram | `raganything/runtime_metrics.py`、`server.py`、focused tests、临时 app/PG/Redis/mock Compose | 29 tests passed、py_compile、OpenSpec strict、diff check；锁定依赖容器 smoke；低资源 Compose 中 migrate、live/ready/metrics、included `/api/auth/login` 均 200，metrics 有 query Histogram 且无敏感/raw/self handler；app/PG/Redis/mock RSS 分别约250/79/6/71MiB | 以既有镜像加当前 `server.py`/helper 只读挂载运行，非容量结论；临时容器/卷/网络/凭据已清理；未访问现有 PostgreSQL、真实模型或生产，未验收 KB/SSE/Worker/Nginx/上传 |

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
