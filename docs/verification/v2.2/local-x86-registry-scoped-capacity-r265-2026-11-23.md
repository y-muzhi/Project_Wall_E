# R265 恢复管理入口的独立容量和实际启停

2026-11-23，独立 `codex/2.2`，依据 V2.01 后端 4.12.3、6.5、7.9。使用实际 Ubuntu 24.04 x86_64、ext4、systemd 255、固定 CPython 3.13.18／SQLite 3.54.1 和 Caddy 2.6.2。运行包准入清单 `aab55f5775aad86fbe17ca3a5d4a40fbaf573d30a26789f27a4eb97d9e23823e`。来宾没有网卡、宿主端口映射或现有数据。

- 原策略位于固定全局路径，按原目录、原代次和原锚固定。同一个路径无法同时保存已封存的旧文件并接受新代次策略。已增加受保护管理目录的显式 `CATALOG` 选择。策略仍核对摘要与原绑定。历史未声明入口继续使用原固定文件，声明位置失效时按资源未就绪处理。
- 离线执行 12 个后端专项文件，共 185 项和 16 个子项通过。包括旧／新策略同时存在、历史默认、显式文件缺失、选择值不合法和缺少 pin。沿用固定 SQLite，既有 Starlette TestClient 产生一项弃用提醒。
- 原生回归按 R258 重做两套隔离普通环境、非空格式 3 快照、原停止未知、未派发容量及两项处置。恢复关闭选择有 33 条当前宿主事实。派发开放回执为 `d5c65f59b6c334ee9e6d7668b63a6479ccaf195e6b53d78e0b05c2e993b251d5`，实际管理 HTTPS 从 `BLOCKED` 读到 `READY`。
- 已恢复的新入口按新策略接受并派发实际 START，systemd 进程重新提供原数据代次的需求读取。相同已用旧控制键提交到新操作返回 409 `MANAGEMENT_KEY_CONFLICT`，该操作版本保持。随后用新登记正常发出 STOP，证明进程退出和管理状态 `SUCCEEDED`。
- 新目录容量文件摘要为 `57460c548a6225f7e1aaf97dcec438b4b78237ce477afb0b5cc9579b816e37f0`，原路径文件摘要始终为 `fd94a9103a66b6e5a97c7197ea466f84285f8ff14e7fc442193f62d11e40f1a4`。原管理数据库、停止原回执和独立集成数据保全，来宾退出。仍活跃运行、异机和生产按各自证据处理。

原生操作使用 `prepare-registry-recovery-entry`、`admit-registry-recovery-entry`、`open-registry-recovery-dispatch`、`observe-environment-control`、`start-runtime` 和 `stop-runtime`。原非空恢复边界见 [R258](local-x86-nonempty-registry-recovery-r258-2026-11-23.md)。
