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
