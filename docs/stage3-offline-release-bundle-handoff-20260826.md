# Stage 3 离线发布包交接

日期：2026-08-26（Asia/Shanghai）

## 交付物与身份

- 离线包：`D:\stage3-offline-release-bundle-20260826`（run-owned，不提交仓库）。
- Candidate：`9798feddb37a9e8ade6ffdda9306df7ff33d8361`，镜像
  `raganything-stage3-candidate:9798feddb37a9e8ade6ffdda9306df7ff33d8361`，
  `linux/amd64`，OCI revision 完全一致，digest
  `sha256:0edb6dc425c350ee8792d3a438eeacf35a7c3f473a4f66fdb2c7359c2a1b8bea`。
- Rollback：`36c2ddaa01b5a2025d6d44980e174d1c2023be10`，镜像
  `raganything-acceptance:36c2ddaa01b5a2025d6d44980e174d1c2023be10`，
  `linux/amd64`，OCI revision 完全一致，digest
  `sha256:77657a04fbc61c2e56660e09602bd7241d2d1921280e642d5eef5ae4fe79c08b`。
- `git merge-base --is-ancestor rollback candidate` 已通过；正式隔离 evidence 为既有、脱敏的
  `stage3-evidence.json`，其中 repair budget 为 0、cleanup 为 passed。

包内以 `SHA256SUMS` 覆盖 candidate/rollback/pgvector/Redis/Nginx 镜像归档、candidate Git archive、
迁移 SQL 和 manifest checksum、OCI/ancestry manifest、`deploy.ps1`/远端脚本 hash、Compose 静态资产、
名称级 secret references、主机前置条件、迁移/备份/恢复/回滚 runbook 与验收清单。包不含 `.env`、DSN、
Authorization、端点、用户数据、原始 provider 响应或原始日志。

## 新服务器前置条件

新主机必须为 `linux/amd64`，至少 4 vCPU、8 GiB RAM、40 GiB 可用磁盘、受支持 Docker Engine 与 Compose v2；
还须具备受管 secret manager、可验证备份 custody、PostgreSQL、Redis、Nginx 和 Prometheus/exporter 所需网络。
配置只能由 secret manager 注入，所需引用仅记录在包内 `requirements/secret-references.txt`。

## 执行顺序与门禁

1. 校验 `SHA256SUMS`，并导入所有镜像归档后检查 digest、revision、`linux/amd64` 和 Python/import smoke。
2. 在唯一、loopback-only 的 disposable Compose project 上执行 candidate health；切换/重启到 rollback 后再次检查 health；只清理该 project、其具名卷和临时目录。
3. 对新服务器执行迁移 `status`、`plan`、`verify`；仅在已验证备份、`MIGRATION_BACKUP_ACKNOWLEDGED=true` 和人工批准后，才可考虑 apply。不得改写历史 migration 或跳过 checksum conflict。
4. 发布后逐项验收 `/api/live`、`/api/ready`、`/api/health`、Worker、PostgreSQL、Redis、Nginx、重启次数、Prometheus/告警和合成登录/授权检索/引用业务流程；生产回滚仍遵循已验证的备份恢复 runbook。

## 离线恢复演练与边界

同一 candidate/rollback 镜像归档已在本地 isolated run 中完成 import、candidate Compose health、rollback Compose health 和 manifest-owned cleanup；foreign Docker resources 保持不变。当前包的两份 app archive checksum 与该成功演练使用的归档一致。一次后续 D: 包健康复验的 Compose 启动失败已在同一会话清理，未留下 run-owned 容器、网络、卷或临时 secret；它不推翻前述已通过的等值 archive 演练，也不构成生产风险。

没有访问云端、已到期服务器、生产配置、生产数据库或生产数据；没有执行生产部署、生产迁移、生产备份/恢复或生产数据操作。外部真实 provider、真实生产浏览器 UAT、Prometheus/Alertmanager 新环境演练仍是新服务器上线前的独立门禁。

## 2026-08-26 离线资格复核

只读验证入口为：

```powershell
.venv\Scripts\python.exe scripts\verify_stage3_offline_bundle.py --bundle D:\stage3-offline-release-bundle-20260826 --git-root C:\Users\98014\知元
```

它已核验 73 个文件、`SHA256SUMS` 自身、Git SHA/祖先关系、OCI index
descriptor/config label/platform、迁移和部署脚本映射、secret 名称和 archive
路径安全。当前基线 `SHA256SUMS` SHA256 仍为
`b7576624c7ed2cb1eddcc151b4681501ee726dc48929ea75f5e8b99309150d41`。

新服务器只读 preflight 入口为
`python scripts/stage3_offline_preflight.py --bundle .`；DNS、TLS、provider
和 backup custody 只能报告为 `pending-external`。发布状态机的唯一 dry-run
入口为 `python scripts/stage3_offline_release_dry_run.py --fixture <fixture.json>`；
它不含 SSH、Docker、部署脚本、迁移或数据库调用，并固定 app-first、nginx-second，
健康/部署失败仅执行一次 rollback，rollback 失败 hard-stop。

**当前资格：not-qualified。** D: 包内旧 rehearsal 脚本使用仅含十六进制的
bootstrap password，Candidate App 在隔离 Compose 启动时被密码策略拒绝；迁移、
PostgreSQL、Redis 和 mock provider 已正常，但 App/Nginx health 未通过。工作区
修复已用 focused tests 覆盖，但没有修改这个已校验包或重新生成其镜像 archive，
故尚未取得两轮完整 candidate -> rollback clean-room evidence，也未执行新的
disaster recovery。不得标记 `offline-release-qualified`、`production-deployed`
或 `production-accepted`。

## v2 重签与资格复核

`D:\stage3-offline-release-bundle-20260826-v2` 以原包根摘要
`b7576624c7ed2cb1eddcc151b4681501ee726dc48929ea75f5e8b99309150d41`
为 provenance 输入，逐字节复制五个 archive；v2 的 76 文件根摘要为
`e853de298fd8b487d3eea793943fc6f8dcc87e7a5333d8ea61f65cc1e69ff1ae`。
manifest 分别绑定 Product Candidate `9798feddb37a9e8ade6ffdda9306df7ff33d8361`、
Rollback `36c2ddaa01b5a2025d6d44980e174d1c2023be10` 与 Package tooling
`695d94b96a55b02ca88e008963c3d7e83bf81024`。v2 verifier 通过，五个 archive
checksum 与原包一致；bootstrap password 每个 clean-room run 都使用仅对子进程注入的
策略合规 CSPRNG 值。

两个独立 archive-only clean-room 已通过：
`stage3-offline-422ee06b90f8` 和 `stage3-offline-783595c94836` 都完成 archive
verify/import、candidate health、rollback health 与 cleanup。两轮前后 foreign Docker
container/network/volume inventory count/hash 相同。Disposable PostgreSQL/Redis DR
`stage3-v2-dr-3b6b83a5e078` 完成 synthetic RBAC/minimal-KB backup、destroy、restore，
并恢复 40 条 migration history、5 个 canonical roles、1 个 synthetic user、1 个 KB。

Docker Scout `v1.23.1` 的本地 archive SBOM 生成已启动；其 cache 显示没有本地 CVE
database 或 cached SBOM。因此 vulnerability snapshot 必须记录
`scanner_database_unavailable`，不得表述为最新扫描。在提供可验证的离线 CVE database
及扫描时间前，**v2 仍为 not-qualified**，不得标记 `offline-release-qualified`。
本轮未访问云端、未生产部署、未生产迁移、未操作生产数据。
