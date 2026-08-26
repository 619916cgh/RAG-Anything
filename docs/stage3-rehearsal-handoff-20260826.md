# Stage 3 Rehearsal Handoff

日期：2026-08-26（Asia/Shanghai）

本轮使用 clean detached candidate `665160126dea00c2fa540b8024cc41bc5b222dbb`，rollback 基线为 `36c2ddaa01b5a2025d6d44980e174d1c2023be10`。candidate image 为 `raganything-stage3-candidate:665160126dea00c2fa540b8024cc41bc5b222dbb`，OCI revision 与 candidate 完全一致，platform 为 `linux/amd64`，digest 为 `sha256:c0277d19ffe2bd9b5197a8ca5509a50ceeaeb1e53c91c82f136dee3166bb4b7c`。rollback image 为 `raganything-acceptance:36c2ddaa01b5a2025d6d44980e174d1c2023be10`，OCI revision 与 rollback SHA 一致，platform 为 `linux/amd64`，digest 为 `sha256:77657a04fbc61c2e56660e09602bd7241d2d1921280e642d5eef5ae4fe79c08b`；两者 identity 与 digest 均不同，且均通过 Python/import smoke。

正式 Run ID 为 `stage3-6651601-65438f41`，脱敏 evidence 位于 `C:\Users\98014\AppData\Local\Temp\stage3-6651601-65438f41-evidence-final2\stage3-evidence.json`。`inventory`、run-owned `backup/restore`、candidate Compose `compose-up`、live/ready/health、migration fresh/upgrade/repeat/intentional-failure 和五级 RBAC 均通过；`video-worker-sse` 在 `segment-validation` 失败。该 failure fingerprint 已执行初始尝试加两次 retry，预算耗尽，Stage 3 按 hard stop 规则未执行 rollback、concurrency、browser、observability 或后续 cleanup stages。外层 Stage 3 cleanup 与内层 acceptance cleanup 均通过；run-owned PostgreSQL、网络、卷、备份预备目录和容器已清理，foreign Docker resources untouched。

本轮未执行生产部署、生产迁移、生产备份/恢复或生产数据操作。真实 provider、browser UAT、并发 1/3/5、SSE/citation、recovery sampling 和 rollback runtime 仍未验收；OpenSpec 4.1 保持未完成，不能将本轮标记为 isolated Stage 3 pass。
