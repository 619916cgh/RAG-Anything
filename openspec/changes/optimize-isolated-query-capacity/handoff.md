# 隔离查询容量优化交接（2026-08-19）

## 给新对话的起始指令

继续执行 OpenSpec change `optimize-isolated-query-capacity`。先完整阅读
`PROJECT_SUMMARY.md`、本文件、该 change 的 `proposal.md`、`design.md`、
`tasks.md` 和相关 spec，再核验工作区，而不是根据本交接直接假定运行环境
仍然相同。仓库工作区并行且很脏：保留所有非本任务改动，不得使用 reset、
checkout、prune 或宽泛的 Docker 清理。

本 change 仍处于归因阶段。当前目标是用隔离、mock-backed 的 Linux Compose
环境获得十并发 CPU 热点证据；在证据出现前，不修改业务查询路径，不部署，
也不宣称容量提高。

## 已证实的基线

证据报告：`outputs/isolated-cloud-perf/cloud-capacity-20260819.md`。

- 云端隔离栈为单 app，限制为 2 CPU / 3 GiB；使用临时 PostgreSQL、Redis、
  Marker、Nginx、mock provider、临时卷、随机测试身份和 loopback Nginx。
- 所有模型请求指向内部 mock；未读取 `.env`，未访问生产 PostgreSQL、卷、
  数据、模型端点或生产运行进程。生产只允许固定容器状态/重启数和
  `127.0.0.1` 的 `/api/live`、`/api/ready` 只读探针。
- 1 用户冷/热基线均为 55/55 成功；5 用户为 5,184/5,184 成功，TTFT P95
  409 ms、完整响应 P95 991 ms。
- 10 用户为 773/773 成功，但 app CPU 连续三次为 89.28%、95.42%、92.06%，
  触发连续三样本超过 85% 的停止规则。RSS 峰值约 920 MiB，恢复后 CPU 约
  0.21%，所以已证实边界是 CPU，不是内存、错误率或连接耗尽。
- 随后短窗口复现 10 用户 216/216 成功、TTFT P95 约 489 ms、完整 P95 约
  919 ms，并再次触发同一资源停止条件。
- 不得由此推断 20/35/50 并发、真实模型、浏览器、多实例或生产容量。

上传结论与当前优化无关：文本单任务和 3 并发 retrieval-ready；文本 5 并发
受同一 app CPU 门限停止；PDF 因离线 Docling layout 模型未预置而
`pdf_page_coverage_incomplete`，不是已确认的 Marker 容量问题。

## 已完成的代码与审查

当前未提交 profiling 实现只属于测试镜像层：

- `tests/perf/Dockerfile.cloud-capacity-app` 在 `RAGANYTHING_ENV=performance`
  和 `PERF_CPU_PROFILING=1` 同时满足时，向测试镜像注入随机 key 保护的
  内部 start/stop 路由；生产 Dockerfile、生产 Compose 和生产 schema 不变。
- `scripts/run_isolated_cloud_perf.sh profile` 只接受 manifest-owned 临时 app
  容器，使用 loopback 端口及运行期随机 key 控制 1--60 秒的 cProfile 窗口，
  将 pstats 从临时容器导出、汇总后立即删除原始 pstats。
- `scripts/cloud_perf_manifest.py` 仅发布 `/app/` 函数的位置、调用数、self/
  cumulative CPU 秒数和受限时间元数据；不发布源码、日志、凭据或容器外路径。
- `tests/perf/test_cloud_perf_contract.py` 覆盖 profiling 仅在 performance
  镜像、随机 key、所有权和脱敏汇总等合约。当前本地性能工具测试共 24 项通过，
  另已通过 `py_compile`、`git diff --check` 和 OpenSpec strict validation；
  Linux runtime endpoint 验收仍未完成。

已完成的只读代码审查结论：

- `raganything/dependencies.py:authenticated_sse_events()` 会在每个受保护
  SSE 事件上重新检查 account session；mock 的 16-token stream 每请求约有
  18--20 个此类事件，可能带来约 36--40 次额外 PostgreSQL read。
- 这只是高概率放大项，尚非函数级 CPU 根因。任何请求内缓存会引入撤销、
  禁用、归档或 session-generation 生效窗口，未经 profile 和确定性安全测试
  不得实施。
- app 日志还曾显示会话摘要阈值后的并发 summary 生成；同样只是候选，不能
  先行优化。

## 下一步的严格执行顺序

1. 对当前代码运行以下本地检查。Windows 本机没有可用 bash 时，`bash -n`
   不是阻塞证据；Linux 运行时验收在云端执行。

   ```powershell
   .\.venv\Scripts\python.exe -m pytest tests\perf\test_cloud_perf_contract.py -q
   .\.venv\Scripts\python.exe -m py_compile scripts\cloud_perf_manifest.py
   git diff --check -- scripts/cloud_perf_manifest.py scripts/run_isolated_cloud_perf.sh tests/perf/compose.cloud.perf.yml tests/perf/Dockerfile.cloud-capacity-app tests/perf/test_cloud_perf_contract.py openspec/changes/optimize-isolated-query-capacity
   openspec validate optimize-isolated-query-capacity --strict
   ```

2. 在云端先只读核验上次临时 run 的容器、卷、网络均已清理，并复测生产五个
   固定容器、两个 loopback health probe 的状态/重启数。若生产探针异常，停止
   本任务并报告，不排障生产。

3. 仅通过既有非交互 SSH 配置传输最小控制包到远端 `0700` 的 `/tmp` 目录。
   控制包只能含 perf runner、manifest、bootstrap、workload、collector、cloud
   Compose、测试 Dockerfile、mock provider、固定文本/PDF fixture；不得传送
   `.env`、部署配置、生产数据或模型。

4. 对已核验的本地基础 app image 临时打 tag，以 `--pull=false --network=none`
   构建本次带 run label 的 `raganything-perf-capacity:<run-id>`。该 image 是
   测试工件，绝不能作为生产 image 或替换生产容器。

5. 使用 `PERF_RATE_LIMIT_MODE=capacity` 和 `PERF_ENABLE_CPU_PROFILE=1` 启动
   完整隔离栈；先 bootstrap 10 个身份并运行 readiness。只有 10/10
   retrieval-ready 且 source 非空才继续。

6. 启动 5 秒资源采集和约 90 秒 10 VU query workload；5 秒后执行 10 秒
   profile。验收 `cpu-profile.json` 为 `available: true`，且只含 `/app/`
   汇总、调用数、self/cumulative 时间，无 raw pstats、凭据或外部路径。

7. 至少继续采集 60 秒恢复证据，然后先执行 runner 的 `down`。仅在 runner
   证明不存在引用容器后，删除本 run 的临时 base/capacity image tag 和控制包。
   不使用 `docker system prune`、`docker volume prune`，不删除生产 image、卷
   或数据。

8. 只有 profile 在持续高 CPU 窗口稳定指向可避免的应用代码，才实施一个最小
   优化并补保护 SSE、撤销/禁用/归档/session generation、事件排序、会话
   持久化和 metrics 的聚焦测试。然后在 profiling 关闭时，以完全相同的
   2 CPU/3 GiB、mock、fixture、Nginx、停止规则重测 5/10 VU。10 VU 通过前
   不允许运行 20 VU；10 VU 仍失败则记录边界，不做推测性改动。

## 明确禁止项

- 不提高 85% CPU 阈值，不增加 `SERVER_WORKERS`，不更改生产限流策略。
- 不移除或弱化逐 SSE event 授权校验，不使用共享 session 缓存。
- 不访问生产 `.env`、PostgreSQL、卷、上传、索引、真实模型、宿主 PID 或
  production profiler；失败的 `py-spy` sidecar 镜像拉取不得通过绕过镜像
  代理或宿主 `perf` 恢复。
- 不执行生产部署，直到优化有 profile 证据、聚焦测试和可比重测结果。即使
  后续需要发布，测试专用 Dockerfile/Compose/profile endpoint 也不进入生产
  镜像或运行配置。

## 提交与部署边界

用户要求后续提交与部署包含本轮改动，但提交必须按任务白名单暂存，不能把当前
脏工作区的其他功能一起提交。当前性能任务的候选白名单为：

```text
openspec/changes/run-isolated-cloud-capacity-benchmark/**
openspec/changes/optimize-isolated-query-capacity/**
scripts/bootstrap_perf_run.py
scripts/collect_perf_resources.py
scripts/cloud_perf_manifest.py
scripts/run_cloud_perf_workload.py
scripts/run_isolated_cloud_perf.sh
tests/perf/Dockerfile.cloud-capacity-app
tests/perf/compose.cloud.perf.yml
tests/perf/fixtures/cloud_fixture.pdf
tests/perf/test_cloud_perf_contract.py
tests/perf/test_perf_tool_units.py
PROJECT_SUMMARY.md  (仅在确认其现有大范围压缩改动由当前协调者拥有时)
```

`PROJECT_SUMMARY.md` 在本对话开始时已经是大范围修改，归属不明。提交前必须
先确认它不是并行任务的内容；若不能确认，避免暂存它，并在提交说明中明确
summary 同步待协调。性能报告位于 `outputs/`，作为证据保留，不应因被忽略而
强行纳入发布包。

现阶段不应生产部署：这些变更尚未完成 1.3 归因、2.x 业务优化和 3.x 可比
重测；且测试 Dockerfile 有意包含容量模式限流覆盖和 profiling route。完成后
若用户仍要求部署，先提交仅白名单内文件并获取完整 40 位 commit SHA，再按
项目规定使用根目录 `deploy.ps1 -Commit <SHA>`。不得逐文件同步或用工作区
直接发布；发布后只做候选 image、容器 health/restart、直连及 Nginx health
的独立只读验收。

## OpenSpec 状态

- `run-isolated-cloud-capacity-benchmark` 的任务已勾选完成，代表原始隔离
  基准已交付，不代表优化已完成。
- `optimize-isolated-query-capacity` 的任务均保持未勾选。1.1/1.2 已有实现和
  初步测试，但最终 Linux runtime validation 尚未完成；1.3 及之后均未完成。
- 每次使用 OpenSpec apply/归档前，遵守仓库 `AGENTS.md` 的多专家调度要求，
  并在最终测量后更新 `PROJECT_SUMMARY.md` 和本 change 的报告。
