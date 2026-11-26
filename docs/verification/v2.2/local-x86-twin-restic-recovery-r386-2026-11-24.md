# R386 两个真实普通库的本地 Restic 发布、取回和恢复

2026-11-24（香港时间），独立 `codex/2.2`。无网卡 Ubuntu 24.04 x86_64、ext4，沿用 [R381 固定运行包](local-x86-host-freeze-dispatch-r379-r381-2026-11-24.md)。两套不同用户组、业务根、数据库及 Restic 本地仓库。实际 Restic 0.19.1，公开 Linux x86_64 归档 SHA256 `f415415624dcc452f2a02b8c33641791a8c6d6d3b65bbb3543fcf9a25151585c`，原生二进制 SHA256 `20d4142678d0d95ec11a4759def1b73fd9190abc9ca19e4b62d067c0b387e639`。[官方发行](https://github.com/restic/restic/releases/tag/v0.19.1)

- 两站经真实固定程序和 Caddy HTTPS 各自建需求、建文档、保存并正常停止。各自以维护身份执行固定 `capture-database`、`check-backup-coverage`、`seal-result-index`、`restore-database`、`check-recovery-chain` 和 `seal-backup-package`。每站封存 5 条原请求结果。初步恢复已独立核对 SQLite 绑定、完整性、外键和正文。
- 两份实际普通包经固定 `publish-backup-snapshot` 写入两份不共用凭据的本地仓库。每个发布在真实原快照上核对取回，原键重放保持同一回执及文件身份，每仓库仅一个快照。各 1,066,347 字节、19 项快照条目。
- `retrieve-backup-snapshot` 分别拒绝换入另一仓库快照 ID，两个接收目录均保持无残留。正确取回后，用相同固定 Restic 在各自目录验证、物化并执行 `verify-backup-package`、`rehearse-backup-package`。分别生成独立新代次，保存正文逐站读回且无对方正文，完整性和外键通过。重播同一次演练读回原回执，源环境的锚、控制、数据库和锁目录身份保持。
- 开发包摘要 `b5a150c4c83710c606741c95b57968a7113ba39f5575213944ff04a727eef3d5`，快照 `37252196dfeb2c790fa37601230d6b071aab50399bfb9f5df001e3c40643d354`。集成包摘要 `7dc5983f4ace267d425f531833c98b56fa24ab9d04bc802c7b173067e2e6f1c7`，快照 `bab49d9f294f703a97adfd522bd8c82b2832ecde1b004cdd23f96ccd47bdaa37`。
- 直链首次连接重置，从官方发布 API 按资产 ID 续取并完整校验。首份验证脚本错读了拒绝时的输出通道，调整为固定 CLI 的 stderr 后，从新的隔离普通数据库复验。最终 `r386-retrieval` 退出 0，普通服务和网关均已结束。

本单元验证同一宿主上物理分开的本地仓库及原生应用备份。真实腾讯 COS、异机仓库、RPO 和生产恢复分别验收。
