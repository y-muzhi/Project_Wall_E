# WALL-E V2.2 Linux 环境准备验证

2026-11-20（Asia/Hong_Kong）。专用 Ubuntu 24.04 ARM64／ext4 验证机，运行用户与维护用户通过 setpriv 使用隔离的测试 UID/GID，未新增系统账户。受保护程序快照取自 `codex/v2.2-development`，HEAD `a0f40592702cb702ed928849ac540479c22c224f` 加 A1—A3 实施文件及 V2.01 后端原件。验证入口为受保护的 `/opt/walle-v22-validation/host-r3/runtime.py`，执行环境无模型凭据或业务监听。

| 检查 | 实际操作及结果 |
| --- | --- |
| 固定运行包 | 在 `arm64-r3` 新 prefix 重建 CPython 3.13.18、私有 SQLite 3.54.1，复用 31 项原 wheel hash 锁离线安装，pip check 通过。封存运行文件 4325 项、宿主库 19 项，并核对 C 锁绑定进入清单。固定入口 `probe` 通过。 |
| 同结构实证 | 固定入口 `build-schema --release-id db22-arm64-r3` 成功，r2/r3 对象 SHA256 一致。r3 实际加载绑定、原来源核对和错环境拒绝通过。 |
| 两套安装 | `environment_provision.main` 通过，均使用不同 root 记录、环境/代次及应用/维护/共享组。前端静态包来源于各自工作区的独立构建。域名与凭据尚未接入。 |
| 原操作准备 | `environment --action prepare` 创建固定意图、初始进度和 CLOSED；随后 `--action check` 返回退出 3 与 INITIALIZATION_INCOMPLETE，数据库仍不存在。 |
| 开发环境中断 | 在真实固定运行包的夹具中，于 TARGET_BOUND 落盘、执行 DDL 前进程直接退出 83。新进程只核对返回退出 3。原 ID／原摘要执行 continue 后 INITIALIZED，第二次 ALREADY_INITIALIZED。 |
| 集成环境中断 | 在 SQL 提交后、记录 DATABASE_VERIFIED 前进程直接退出 84。check 使用新 SQLite 连接核对归属、结构和完整性，补原 COMPLETE；再次 continue 返回 ALREADY_INITIALIZED。 |
| 无归属文件和宿主保持 | 一次可丢弃隔离夹具在 O_EXCL 建立空文件后、写 TARGET_BOUND 前骤停。check 与 continue 均保持原零字节 inode 并返回待核实，错误意图被拒，宿主 hold 状态拒绝准入。仅清理该次夹具。 |
| 应用身份核对与排他 | 两套用各自应用身份 diagnose，均返回 DATABASE_READY、admission=CLOSED。应用持锁时独立维护进程 observe 得到真实 PID，第二次应用准入被 ENVIRONMENT_ALREADY_RUNNING 拒绝。释放后无持有者。应用用维护动作被拒绝。 |
| 文件权限边界 | 两套应用 UID 直接打开对方主库，由内核返回 PermissionError。业务目录和锁访问在环境组间隔离。 |
| 本机检查 | Ruff 格式及改动文件 F 检查通过；基础设施全目录 F 检查另发现 3 个旧文件问题，本轮未改既有文件。 |

首次验证工具误用 SSH 登录用户检查开发数据目录，真实权限返回拒绝。该次原意图已落盘，尚未创建数据库。修正验证身份后重读原意图和摘要，未复制意图或重建目录。

## 固定输入与安装记录

- 运行包 SHA256 `5d2204af9a49fd8de30d16422a2781c4f2e1b7a9a487023e4961ad6cfe35427a`，外部 pin 位于 `/opt/walle-v22-validation/host-r3/arm64-r3.sha256`。
- Schema manifest SHA256 `1cc7529f98285f4714b2e2a9afdc87fc218808d1844801a1a513be796f8b02c4`，对象契约 SHA256 `ed057e0ddadbcdbb47bd8e78c541cf009fd719c397ffe79579d3ae2684802fc3`。
- 开发环境 `0e3cce9f-1c2e-46a3-931c-5951053db4ca`，代次 `aa79f3ae-9636-4803-aa98-ab0e9e895861`，安装 pin `bf30d3b9142d0483d72de67cf2bc6a0adf3b8aadbf15817ba91ad317bb8b612e`。原操作 `23e128e6-ad11-4e32-987e-2c0600df9a36`，意图 `e9e615f28d41324fee7172ab8e0ec9adb251b0b9d837b4cd0c9b1739ebd3be0d`。
- 集成环境 `ca8bea4e-f95f-442f-af4a-8453a17c7bd6`，代次 `d7d55b4c-5df8-4ba5-9381-8fd66184e1f1`，安装 pin `14f973c5deb2b92c7a0bec2dd01784002eced91eb2399f449fe3c3978514cb49`。原操作 `0ce398c3-5a15-40f6-95f0-c91ed9dbf066`，意图 `55321204962da85da91f62c2060a2b60eaeea6a9d47ef3dafa042788a52098b4`。

环境路径为 `/opt/walle-v22-validation/environments-a3-r3/<environment_id>`，程序快照 `/opt/walle-v22-validation/program-a3-r3`。根路径已分成 lock、control、data、runtime、log、temporary、frontend、maintenance。运行包、数据库、初始化操作及安装记录均为后续验证输入，保留这些正式隔离资源。构建与中断夹具临时路径均退出清理。

未覆盖完整 PKG 破坏矩阵、业务异步工作器、真实浏览器及生产接入。独立 B3 记录验证普通业务和正常停止。持续用户服务、业务库、正式规格和已封存 r2 均未修改，未调用模型、计数或 Git 提交推送。
