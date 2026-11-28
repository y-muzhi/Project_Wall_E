# R218 Ubuntu 管理登记重新开放派发

2026-11-23，独立 `codex/2.2`。在 [R204](local-x86-registry-selection-r204-2026-11-23.md) 关闭选择的只读基盘上独立重复 [R211](local-x86-registry-entry-r211-2026-11-23.md) 的候选入口准备和接纳。来宾无网络，Ubuntu x86_64、ext4、固定 Python 3.13.18／SQLite 3.54.1、Caddy 2.6.2，管理 TLS 仅在来宾回环 9444。

- 新登记按实际 `systemctl` 固定摘要重新观察原目录和清册。 `check-registry-recovery-dispatch` 核对真实暂停期间的原快照、选定登记、当前专属 Caddy 配置和新鲜宿主观察，返回 `PAUSED_SOURCE_VERIFIED`、无阻塞项。相同复验读回摘要 `a68627fdb0ad45913e26d6e8fda5567764b142e66388ccc8b22084d5a2c817fb`。
- `open-registry-recovery-dispatch` 拒绝错判定摘要，原暂停仍在且没有退役凭证。正确策略只在该空登记实机开放，旧暂停原字节归档，同一原键重放返回 `e62b2aec8ef9ede765297d892d24418bb6c8c2b98fdadae0fe22a4ea3aa5d7c9`。原管理及两套普通库、普通控制和已选锚摘要均无变化。
- 同一恢复登记在真实管理 HTTPS 中先读回 `BLOCKED`，开放后经独立停启读回 `READY` 及更新的运行 ID。 `observe-registry-dispatch` 只读核对为 `MANAGEMENT_DISPATCH_OPEN`。管理进程和 Caddy 正常退出，来宾退出码为 0。宿主本轮专属 QEMU 进程、临时盘及辅助程序已核对清理。
- 本轮只开放独立空登记，没有派发实际工作或使用真实账号。包含既有未知、正在运行或历史任务的宿主恢复、实际云宿主及生产开放仍待按原保护条件核验。
