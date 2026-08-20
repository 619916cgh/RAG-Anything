# Profile B 50 VU 测试交接（2026-08-20）

## 已完成的隔离诊断

- 直接 50 VU 诊断使用一次性 Profile B mock 栈，应用配额为 8 vCPU / 24 GiB。
  它不是有序 `1 -> 5 -> 10 -> 20 -> 30 -> 40 -> 50` 阶梯证据，不能据此宣称生产
  或真实千问容量。
- `638/638` 请求以完整 SSE 终态成功；未观测到 SSE 顺序错误、重试、OOM、容器重启或
  临时资源泄漏，清理后 manifest-owned 资源数为零，允许的生产健康探针保持正常。
- 应用 CPU 峰值为 8 核配额的 `12.689%`，RSS 峰值为 24 GiB 配额的 `3.429%`。主机
  CPU 和内存并非本次硬停止原因。
- 延迟门禁硬停止：TTFT P95 为 `17.153s`，完整响应 P95 为 `18.512s`，超过 Profile B
  mock 目标 `2.1s / 2.7s`。该结论只说明当前 mock 调用调度/排队路径不满足该 SLO，
  不等价于真实千问吞吐或生产用户容量。
- 已修复一个独立的后端竞态：多 KB 并发初始化时，新 query core 在 query lease 登记前
  可能被 LRU 淘汰，形成固定的 `query_core_acquire` 非成功分类。`KBCache` 现在在同一
  eviction lock 内完成发布、lease 登记和淘汰；回归测试覆盖该顺序。

## 新对话必须实施的后端改动

以下项目是面向真实千问账号的独立 change，建议名称为
`govern-qwen-provider-concurrency`。不要通过提高 `MAX_ASYNC`、HTTP rate limit 或
`SERVER_WORKERS` 代替这些改动。

1. 新增 provider-scoped 准入服务。每一次真实 Qwen LLM/VLM 调用才申请并发 slot，
   流式调用持有到终态、取消或异常后的 `finally` 释放。不得把检索、PostgreSQL、SSE
   写出或整个查询生命周期错误计入 provider slot。
2. 用 PostgreSQL 实现跨 worker/实例的 durable FIFO ticket、租约、TTL/heartbeat 和
   owner fencing。交互查询优先，上传和后台模型工作使用同一全局预算的低优先级队列；
   断连、超时和进程退出必须可回收名额。
3. 将“50 个活跃 SSE 查询”“单用户查询公平性”“本地 LightRAG 检索并发”和“Qwen
   provider 并发/RPM/TPM”拆为独立配置与指标。`MAX_ASYNC` 仅保留为兼容的本地
   LightRAG 参数，不能作为 Qwen 账号配额开关。
4. 为每个非敏感 provider quota scope 配置并校验 concurrency、RPM、TPM、最多 10 秒
   的可取消 FIFO 排队与 `provider_busy` 结果。未显式配置真实账号限额时，拒绝启用
   50 用户模式；初始 provider cap 为 40，待账号模型/RPM/TPM 实测后再调整。
5. 统一包装 Agent 最终回答、查询改写、工具调用、LightRAG 文本/VLM 和 ingestion 的
   Qwen 调用路径。一个用户查询可产生多个模型调用，现有整条 SSE query lease 不能
   当作上游并发限制。
6. 增加 429/`Retry-After` 策略和 provider circuit breaker：仅在首 token 前做有界重试，
   已输出 token 后不重试，避免重复答案或双重持久化。
7. 固化脱敏 SSE 排队语义：`accepted -> queued? -> agent_info/thinking -> token* ->
   done|error`；排队心跳、取消和错误码不得包含上游原文。会话撤销/禁用检查可以限频，
   但首个受保护事件必须复核，后续最多两秒重新复核一次。
8. 增加不含内容或凭据的指标：admission、queue wait、inflight、429/timeout、retry、
   circuit state、TTFT、总耗时、lease 回收和超额拒绝。数据库连接池预算也必须与应用
   worker 数共同校验。
9. 暂时保持 `SERVER_WORKERS=1`。多 worker/多副本需要另一个 change，先解决 KB
   cache、初始化、删除 fencing、revision invalidation 和总连接池预算的跨进程协调。

## 必须补的测试和验收

- 聚焦单元/PG 集成：FIFO、公平性、跨实例上限、TTL/fencing、取消回收、流式 slot 生命周期、
  429 在首 token 前后、circuit breaker、错误脱敏，以及 LightRAG/direct adapter/ingestion
  全部通过同一 wrapper。
- SSE/安全：事件顺序、queue timeout、断连、撤销/禁用、会话持久化和 error propagation。
- 隔离真实千问验收：使用一次性 app/PG/Redis/Nginx、临时身份/KB、限额临时 API key，按
  `10 -> 20 -> 30 -> 40 -> 50` 顺序执行。每阶记录 TTFT、总耗时、queue wait、429/timeout、
  provider active/max、CPU/RSS 与 PG pool wait；硬停止后不继续。
- 50 VU 的业务验收门槛为 TTFT P95 <= 5s、完整响应 P95 <= 15s、无 provider lease 泄漏和
  无超额调用。真实 Qwen 模型、账号 concurrency/RPM/TPM 未提供前，不得声称达到这些指标。

## 明确边界

本次直接 50 VU 是 mock-provider 诊断，不包含真实千问、生产配置/数据/凭据、浏览器、
真实 PDF/Word/Excel 解析或多实例。文档解析应作为低优先级共享 provider 预算工作，不能
侵占交互查询名额。
