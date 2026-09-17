# RAG-Anything 项目核心总结

> 本文件是项目任务的首要导航。实际代码、迁移、运行配置和 OpenSpec 规格优先于本摘要；敏感值、用户数据和运行日志不得写入。

## 0. 元信息与使用规则

| 项目 | 当前值 |
|---|---|
| 最后核验日期 | 2026-09-17（Asia/Shanghai） |
| 核验分支 | `codex/paginate-large-kb-document-summaries` |
| 基准提交 | 当前 HEAD `8a6d5c9e23cf279adf260924e722baa6962e30d2`；Stage 3 离线资格 `f751e54f2e57` |
| 工作区状态 | 2026-09-14 文档交付收口提交后应为干净；以实时 `git status` 为准 |
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

2026-09-17 多模态中文切片修复完成：ODL 空表拦截、caption-only 降级、嵌套图片保留；表格、图片和 chunk 默认中文。聚焦 58 passed/1 skipped，扩展 172 passed/1 skipped，真实 ODL 回放 `table_blocks=0`/`image_blocks=51`；未部署或回填。

2026-09-17 ODL 扫描 PDF OCR：`e729b69` 后修复 `blank` 页漏入 OCR、状态迁移与旧缓存失效；聚焦 49 passed/1 skipped，真实 25 页第 1-25 页覆盖，`blank_pages=[]`。

| 日期 | 任务/change | 类型 | 结果 | 影响范围 | 验证 | 经验/风险 |
|---|---|---|---|---|---|---|
| 2026-09-15 | agent-image-query-recognition-and-preview | 修复/真实链路 | 标签范围下仍执行 VLM；图片理解独立超时并显式报错；规范化 MIME；无知识库文本时视觉描述可作为直接证据；用户消息持久化 JPEG 缩略图并在历史恢复 | Agent 路由、对话元数据、前端消息映射；无迁移或 RBAC 变更 | 后端相关 90 passed、前端 236 passed、Vite build；真实 `weaviate_pricing.png` 被识别并回答为 `Weaviate`；会话 API 返回 50,923 字符 JPEG 预览及图片描述 | 仅本地真实 Provider/API 验证；未执行浏览器 UAT、云端部署或生产验收 |
| 2026-09-15 | new-server-controlled-full-deployment | 受控整栈部署 | 固定提交 `6eb85a69d170f7dcdf1507ebfa2c9edaf92a5b75`、本地 PostgreSQL 快照及 9,816 个持久化文件已部署到新服务器；经用户批准并在已验证云端备份后原子执行不可逆 `037_remove_dag_workflow.sql`，官方迁移器确认 `pending=0`；App、Marker、PostgreSQL、Redis、Nginx 已启动 | 新服务器整栈、数据库、知识库/上传/输出目录和云端 Compose overlay；未迁移旧服务器数据，未修改本地产品源码 | 持久化文件逐项 SHA-256 通过；镜像 ID/amd64 校验；迁移 status/plan/verify；直连与公网 `/api/live`、`/api/ready`、`/api/health` 及首页均 200；认证后 5 KB、2 Agent、抽查 6 会话；服务重启后数据仍可见且容器重启计数 0 | 已证明当前数据恢复、服务健康和认证读取；未执行真实 Provider 问答、新上传 Worker 处理、完整浏览器 UAT、TLS/域名或生产容量验收；云端保留迁移前可读备份 |
| 2026-09-14 | new-server-deployment-preflight | 发布门禁 | 新服务器全新部署请求在本地资格检查停止：`deploy.ps1` 拒绝当前候选，因 Dockerfile、Compose、前端锁文件、036-038 迁移及迁移运行器等变更需要受控基础或迁移发布；未上传、未部署、未修改远端或数据 | 仅本地发布流程；无云端资源、产品运行行为、数据库或数据变更 | `git status` 干净；`deploy.ps1` exit 1；未进入远端发布；现有 SSH 密钥对新目标公钥认证失败 | 不得逐文件同步、密码登录或临时配置绕过；需先完成受控基础镜像和迁移发布，并配置合格的非交互 SSH 目标 |
| 2026-09-14 | doc-deliverables-closeout | 文档交付收口 | 整理并提交已实现功能参数报告、字体版报告、项目详细参数、项目参数清单及生成脚本；清理 DOCX 个人元数据；渲染/解包/外部材料审计产物加入精确忽略规则 | 仅文档、生成脚本和 `.gitignore`；无产品运行行为、迁移或部署变更 | 生成脚本编译、DOCX 包/XML/文本提取、字体或页面 QA 边界、diff/status 检查 | 不构成 Provider、Worker、浏览器、迁移或生产验收；外部材料分析产物不进入仓库 |
| 2026-09-10 | KB capability helper return regression | 修复/回归 | 恢复编辑 capability helper 的返回值，避免 `/api/kb/list` 和编辑权限检查读取 `None` | KB 列表与编辑权限投影；无数据库、迁移或 RBAC 规则变化 | 五角色 capability、KB 列表聚焦测试与编译检查 | 语法编译无法发现缺失业务返回值；媒体交付改动需覆盖共享 KB capability 回归 |
| 2026-09-10 | new-upload-media-delivery-v2 | 实现/生命周期、身份与清理修复 | 修复 finalize 后关闭连接、纯视频缺 upload identity 导致 99% 失败，以及失败上传在文档删除后残留列表；纯多模态状态持久化 `track_id`/`metadata.task_id`，失败任务可按 task ID CAS 删除并取消待运行重试，文档删除优先强身份释放上传行，同名活动任务隔离，PG 任务删除成功后才清本地缓存 | Worker、文档状态、上传列表与删除、媒体契约、重试清理 | 媒体修复相关后端 151 passed/1 skipped 后本轮 60 passed；清理相关后端 68 passed、前端 234 passed、Vite build、compile、相关 OpenSpec strict、summary/diff 通过 | 不回填旧任务；历史无 task ID 仅唯一终态文件名回退，未命中返回 `upload_cleanup_pending`；真实重传、删除 UI、Range 206 与浏览器定位尚未验收 |
| 2026-09-17 | decouple-kb-list-stats-release | 修复/快速发布 | 修复后端加载后首次进入知识库偶发列表超时、刷新才恢复：`/kb/list` 不再同步等待聚合统计，列表元数据立即返回，`stats` 保留兼容的 `unavailable` 占位并由 `/knowledge/stats/batch` 独立补齐；候选提交 `4f278e8da3a111ab850b2e46880e385ca0fdfd5c` | KB 列表路由与回归测试；无迁移、数据库、权限或前端契约变更 | 后端聚焦 12 passed、前端 239 passed、Vite build、compile/diff；云端快速发布 accepted，App running/healthy/restart=0，App 直连 live/ready 200，Nginx live/ready/health 200 | 已完成云端发布健康验收；未执行真实登录浏览器首次进入 KB 的业务 UAT、Worker、Provider 或迁移验收 |
| 2026-09-16 | first-business-route-epoch-auth-race | 修复/浏览器/云端发布 | 修复后端加载完成后首次进入知识库、任意操作卡住随后掉登录：业务路由在挂载 `AuthProvider` 前等待 `/api/health` 的数据 epoch 同步；epoch 变化先清理旧应用存储并 reload，`/demo/` 保持立即渲染 | 前端启动入口与 system-data-epoch/public-demo 合约测试；无后端、API、迁移或数据变更；源码提交 `50a82d1` | 前端单测 239 passed、Vite build、diff check；本地真实会话加延迟 `/api/health` 浏览器回归确认业务壳在 epoch 同步前不挂载、旧 auth 被清除、随后稳定显示登录页且清理前无业务 API 请求；云端快速发布 accepted，App healthy/restart=0，direct live/ready 200，Nginx live/ready/health/frontend 200 | 已完成云端发布健康验收；未做真实 Provider、Worker、迁移或完整生产业务 UAT |
| 2026-09-09 | video54-provenance-bounded-runner | 独立 provenance 有界运行 | 候选 `5477a0f558bcbac5639a13cdc4ce9c3a92d4f6d7` 在 clean detached checkout 通过 preflight；视频仅以脱敏大小与 SHA-256 复制到 run-owned 输入，官方隔离 PostgreSQL 迁移失败后立即停止；upload、task、Worker/document persistence、serializer、mapping 均未到达，未执行 Browser/SSE/Phase A/B/retrieval/video-segments/真实 Provider/生产部署 | 仅 run-owned 临时目录与隔离迁移尝试；无源码、当前数据库或生产资源改动 | evidence：`C:\Users\98014\AppData\Local\Temp\provenance-bounded-run-20260909\evidence.json`；preflight passed，migration failed，cleanup passed；foreign Docker 计数 `2/15/14` 前后不变；输入副本已清理 | `not-releasable`；迁移失败原因按 runner 脱敏为 `migration-runner-failed`，未重试；不得将本轮结果视为 Worker、浏览器、完整 Video 5.4 或生产验收 |
| 2026-09-09 | conversation-summary-threshold-and-injection | 实现/回归 | 摘要默认触发轮数 3→10；普通 RAG/ReAct/CoT 从线程读取已持久化摘要并注入 Prompt，摘要为空/关闭时仍用近期历史；无迁移/API 变更 | 后端 Agent 上下文、配置示例、OpenSpec 规格 | 定向 62 passed、py_compile、OpenSpec strict、diff check 通过 | 未执行真实模型、浏览器或生产验收；近期历史与摘要重叠为既定最小改动 |
| 2026-09-09 | complete-citation-provenance | 实现/隔离 PG/本地 038 修复 | 新增 038 citation_provenance 与 citations 持久化；ODL/文本/图片/视频 provenance、统一 citation DTO、Agent/AutoRepair/Public Demo、前端展示与生命周期 fail-closed 已实现；本地 raganything 已备份并应用 038 | 迁移、解析、查询、Agent、Demo、前端、删除清理 | 后端相关聚焦 221 passed、前端 233 passed、Vite build、OpenSpec strict、diff/compile；隔离 PG fresh/upgrade/repeat/failure/recovery 5 passed，并发/跨 KB 隔离通过；本地 custom backup 已核验 | 仅本地库应用 038，生产仍未；Worker+浏览器链路仍需用新上传 PDF、图片、视频在同 Run 验收，不能以单测/构建/隔离 PG 升级证据 |
| 2026-09-08 | video54-provider-governance-migration-repair | 本地数据库受控迁移修复 | 确认本地 raganything 数据库缺少 036_provider_governance.sql 的三张 Provider Governor 表；先完成 PostgreSQL custom backup 并通过归档可读性检查，再在保持 LF 的临时迁移副本中仅应用 036；未执行不可逆的 037_remove_dag_workflow.sql | 仅本机 PostgreSQL schema；无源码、生产资源或视频测试代码修改 | 备份 SHA-256 已记录于本轮脱敏交接；官方 runner plan/verify 仅报告 036 pending，apply --backup-acknowledged 成功；provider_call_leases、provider_waiters、provider_circuit_state、video_assets、video_segments 均存在，036 history=applied | 解决共享 Worker 前置缺表问题；仍需重新上传/重跑 Video 5.4 才能取得新的 Worker/浏览器证据；037 需单独审阅和批准，不能把本地迁移修复视为生产验收 |
| 2026-09-08 | cloudflare-deployment-boundary | 只读部署核验 | 确认 Cloudflare Pages 可承载 `frontend/dist`，但当前完整应用仍需独立 Docker/Linux 运行 FastAPI、PostgreSQL、Redis、Marker/解析 Worker 与持久化存储；未发现 Wrangler/Workers 配置，未执行云端部署 | 仅部署建议；无产品代码或云资源修改 | 静态核对 `frontend/package.json`、`frontend/vite.config.js`、`docker-compose.yml`、`Dockerfile`、`nginx.conf`、`deploy/volcano-engine-docker.md`；未访问云端资源 | 前端 API 固定同源 `/api`，Pages 单独部署必须配 Worker/Pages Functions 反代或改 API 基址；不可将 Pages/Workers 单独部署结果当作完整生产验收 |
| 2026-09-03 | video54-browser-phase-a-formal | 隔离正式 Phase A | failed：qualified image identity 后，mock run 停在 `browser-desktop-super_admin-new-video-citation-render`；`persisted_citation=0`，assistant/citation/player DOM、visibility、reload、media、Range 均 `not_reached`，Phase A 不通过 | run-owned Compose、PostgreSQL、Redis、mock provider、Browser；已清理 | schema 4 browser evidence `C:\Users\98014\AppData\Local\Temp\video54-phasea-formal-20260903-0400\browser-stage-evidence.json`；SSE/persisted conversation/assistant 已通过；aggregate runner evidence 仍 schema 2，runner output 保留但无 service log artifact | image preflight 已 qualified，但不等同 Phase A；未执行 Phase B、五角色、完整 5.4、生产或真实 Provider |
| 2026-09-08 | kb-qa-citation-provenance-audit | 只读能力核验 | 通用问答溯源解析为 `[来源 文档名]`/`[来源 N]`，结构化字段主要是 `index`、`document_name`、`excerpt`、`file_path`；通用 Agent SSE 当前实际仅序列化视频片段 citation，带资料名、受控媒体和 `start_ms/end_ms`。页码、入库时间、图片所属文档等不是通用 citation；AutoRepair 专用链路另有 `page/section/ingested_at` 富化 | 仅源码/规格核验，无产品改动 | `raganything/citation_parser.py`、`raganything/query/pipeline.py`、`raganything/routers/agent.py`、`raganything/services/video_segments.py`、`frontend/src/pages/AgentChatPage.jsx`、`frontend/src/components/VideoSegmentPlayer.jsx` | 普通文本引用和图片元数据目前未在通用问答 UI 以细粒度定位展示；不可将 AutoRepair 或视频专用字段表述为全局能力 |
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
