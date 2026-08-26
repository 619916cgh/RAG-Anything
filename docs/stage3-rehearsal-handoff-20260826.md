# Stage 3 Rehearsal Handoff

日期：2026-08-26（Asia/Shanghai）

正式收口使用 clean detached candidate `9798feddb37a9e8ade6ffdda9306df7ff33d8361`，rollback 基线为有独立隔离验收记录的 `36c2ddaa01b5a2025d6d44980e174d1c2023be10`。candidate image 为 `raganything-stage3-candidate:9798feddb37a9e8ade6ffdda9306df7ff33d8361`，OCI revision 完全一致，platform 为 `linux/amd64`，digest 为 `sha256:0edb6dc425c350ee8792d3a438eeacf35a7c3f473a4f66fdb2c7359c2a1b8bea`。rollback image 为 `raganything-acceptance:36c2ddaa01b5a2025d6d44980e174d1c2023be10`，OCI revision 完全一致，platform 为 `linux/amd64`，digest 为 `sha256:77657a04fbc61c2e56660e09602bd7241d2d1921280e642d5eef5ae4fe79c08b`；两者 identity 与 digest 均不同，且均通过 Python/import smoke。

正式 Run ID 为 `stage3-9798fed-b31c46f3de5f8926`（acceptance 子运行 `b31c46f3de5f8926`），脱敏 evidence 位于 `C:\Users\98014\AppData\Local\Temp\stage3-9798fed-run\formal\stage3-evidence.json`。`inventory`、run-owned `backup/restore`、candidate Compose `compose-up`、live/ready/health、migration fresh/upgrade/repeat/intentional-failure、TXT/Markdown/retrieval、duplicate、App/Worker recovery、SSE/citation、五级 RBAC、concurrency 1/3/5、recovery sampling、Browser desktop/mobile、observability、video Worker 和 rollback 均通过；修复后重跑使用同一 formal Run 的独立 run-owned acceptance 资源，repair budget 使用 0。外层 Stage 3 cleanup 与内层 acceptance cleanup 均通过；run-owned PostgreSQL、网络、卷、备份预备目录和容器已清理，foreign Docker resources untouched。

本轮未执行生产部署、生产迁移、生产备份/恢复或生产数据操作。外部真实 provider 仍 deferred；Stage 3 browser smoke 使用本机 Chrome headless，非真实用户生产 UAT。OpenSpec 4.1 已完成，正式 evidence 标记 `isolated-stage3-pass`。
