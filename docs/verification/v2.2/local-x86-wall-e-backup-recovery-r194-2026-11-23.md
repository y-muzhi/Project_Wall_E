# R194 本机 Ubuntu 两套实际 WALL-E 文档备份并恢复

2026-11-23，独立工作区 `codex/2.2`。无网卡的 Ubuntu 24.04 x86_64 临时增量盘复用 [R192／R193 实际双 HTTPS 的停机盘](local-x86-caddy-twin-r192-r193-2026-11-23.md)。独立 ext4、原两套固定程序、Python 3.13.18、SQLite 3.54.1。

| 环境 | 实际封存包 SHA256 | 实际独立恢复结果 |
| --- | --- | --- |
| 开发 | `bea0582b4abae4c5b98b67b1ae7b906b416533fccc5bb5909e68844aa480973d` | 原停机快照、库外计数资产索引、5 个原请求结果、两次独立恢复的需求及 Markdown 一致 |
| 集成 | `fea07a9b8d43054fdf8561886ec811cfe25a0ee1978bbbc172fe455b02b0eff2` | 各自的需求及 Markdown、5 个原请求结果和新代次正确，开发内容未串入 |

- 各自维护 UID 从真实只读关闭状态运行固定 `manage_registry.py` 的 `capture-database`、`check-backup-coverage`、`seal-result-index`、`restore-database`、`check-recovery-chain`、`seal-backup-package`。从原封存位置搬到独立根后，用 `verify-backup-package`、`lookup-backup-result`、`rehearse-backup-package` 读取及恢复。重试返回同一捕获、封装及恢复事实。独立读库确认完整性、外键、原环境、已保存正文、原结果及各自的新代次，恢复回执保持外发冻结，两套源主库、原安装、原控制摘要保持相同。初次夹具误将完整包演练回执当成单项数据库回执，调整断言为实际的 `BACKUP_PACKAGE_DATA_REHEARSED` 后复验通过。
- 保持目标范围内的固定 Restic 0.19.1 及独立新仓库；开发环境不可变封存包通过 `publish-backup-snapshot`、`retrieve-backup-snapshot` 本地发布并实际取回。原操作重试对应同一个快照，仓库只有该一条。固定快照 ID 为 `0ff5a135c9a26a60aa7eeb19e81fd7168af63910532363304ecfa9c94f57801a`，共 19 项、1,066,345 字节，取回临时目录空。测试包与临时凭据仅存在验证盘。
- 本次记录固定工具的真实本机执行。管理登记升级为 `LOCAL_VERIFIED` 的接口本轮未在 Linux 受管链路重演。计数资产经现行索引规则核实，本轮未执行真实计数请求。异机仓库、生产环境恢复和活动部署切换待另验。
