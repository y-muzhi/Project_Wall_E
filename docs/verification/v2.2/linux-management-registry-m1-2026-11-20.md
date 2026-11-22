# WALL-E V2.2 独立管理登记库 M1

2026-11-20（Asia/Hong_Kong）。Linux `codex/v2.2-development` 的 M1 文件已用路径和源字节摘要同步。专用 Ubuntu ARM64、固定 r3 Python 3.13.18／SQLite 3.54.1、受保护程序 `/opt/walle-v22-validation/program-m1-r3` 摘要 `065a8cba10dddf930e5e754d43f62567267c9b1bab6c2787992c44f760c9e44d`。

- 实际入口 `tools/linux_runtime/manage_registry.py` 的 `prepare` 只由安装员建立两个全新的固定布局、稳定锁和空数据库文件。两个临时管理身份的 `manager_id`、登记代次、数据库 inode 和数据根各自独立。重复 prepare、错误锚摘要、另一身份以及初始化前普通诊断均拒绝，文件及原锚保持原字节。
- 两次 `initialize` 经固定运行包建独立 Schema 1、完整性核查和重开，实际启用 WAL、FULL、外键。对同一登记再次 initialize 返回原验证事实。真实独立 POSIX 持锁进程使第一套诊断拒绝，第二套同期仍可读，释放后第一套可读取原状态。
- 模拟提交成功但最终回执未发布，普通 diagnose 和重复 initialize 报待核实。显式 `reconcile` 重新查实际库后补同内容回执，无第二次 DDL。移开数据库文件、同名符号链接和真实 SQLite 头部损坏均拒绝，保留原对象或现场。
- 项目锁定 Ruff 0.17.3 的格式及 F 检查通过，Windows 用内存 SQLite 预检 10 个独立 Schema 对象和外键。正式运行证据来自固定 Linux 运行包。本次临时资料只在 `/opt/walle-v22-validation/management-m1-check-*` 的唯一分配目录内，所有本轮管理进程及数据已收尾。未启动管理网络服务或访问业务库。

这是独立管理存储基础。环境登记和真实资源读取、普通启停、集成交付事务、发布及恢复换代仍待落实。
