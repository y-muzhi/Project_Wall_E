# V2.2 R328 停止后备份门槛与可搬移封存包

2026-11-24（香港时间）。使用 [R325 的真实双环境停机盘](local-x86-two-environment-stop-r325-r327-2026-11-24.md) 的无网卡派生来宾，固定 CPython 3.13.18、SQLite 3.54.1、ext4。无宿主端口映射。

- 以开发站原停机待核实的控制修订 4 和确切安装，执行真实 `capture-database` 并返回 `DATABASE_CAPTURE_SOURCE_CHANGED`。无捕获内容写入，原控制、稳定锁、数据库和存在的侧文件保持。
- 集成站原控制为 `CLOSED/NORMAL_STOP`。实际 `capture-database` 和 `check-backup-coverage` 成功。捕获回执 `e4f110a156fb5c1cced8c193d34e41e41810caf4a495466729bdcbb3d45006a0`，覆盖证明 `01f9d73ee0710cd0b887ec211e076db81440b809949544c018da148f2741bf68`。同计划重放一致。随后 `seal-result-index` 保全 5 条，`restore-database` 完成第一份独立恢复，`check-recovery-chain` 将原库、证据及该恢复绑定。
- `seal-backup-package` 真实封存并可重放。初次测试夹具在父目录寻找清单，实际清单位于固定 `package` 子目录。关闭来宾后从保留原盘续跑，对同一原封存读回一致，包摘要 `b0a4ed446e100a54d3ba23f260cca26e92ad77ba94b93c1eee2cb45c21f1bcdd`，共 13 个文件。
- 将同字节包复制到另一受保护根，按该根实际文件身份和原清单执行 `verify-backup-package`、`lookup-backup-result`，原操作状态及 HTTP 状态可按原键复核。实际 `rehearse-backup-package` 在第二个独立数据代次成功并能原键重放，原结果索引摘要 `209504a2a182830ed7039e76015f8cc869173e4323fff560ddda6ae43ae3d8a9`。
- 两份新数据库用固定 SQLite 独立只读核对完整性、外键、各自绑定代次和集成原 Markdown。两套原数据根和原控制、稳态锁摘要不变，原封存包保持。

这里覆盖本机封存、代次恢复与无停写凭证时拒绝。正式发布开放、管理服务最终落账及真正异机 COS 仍有独立验收。
