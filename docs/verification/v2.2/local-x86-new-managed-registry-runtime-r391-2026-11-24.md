# R391 当前管理库、实际工作树和真实受管启停

2026-11-24（香港时间），独立 `codex/2.2`。无网卡 Ubuntu 24.04 x86_64，沿用 [R386 的同版本真实普通环境](local-x86-twin-restic-recovery-r386-2026-11-24.md)。独立来宾内新管理登记、实际 ext4、systemd 和固定 CPython 3.13.18／SQLite 3.54.1。业务 Unix 套接字和管理命令没有宿主端口。

- 实际 `manage_registry.py prepare`、`initialize` 建独立管理库。从只读 Git bundle 拉取既有提交 `deacba8a9545122f35a2f85c125a354205e06461`，创建开发、集成两个真实工作树，分支、目录 inode 和安装对象分开。固定 `observe-attach` 核对实际 Git 与安装，再用真实管理 `ATTACH` 登记，两份原键都可重放。
- 集成站经 `observe-environment-control` 核对正常关闭，原管理 `START` 受理并保有内存、CPU、任务数、运行槽四项容量。向专属应用账号临时加测试组后，真实 `start-runtime` 返回 `MANAGEMENT_RESOURCE_UNVERIFIED`。没有新的宿主启动记录或 systemd 单元，原控制、数据库、原键和四项预留原样。
- 撤回测试组后，同一原管理请求和固定启动策略启用真实应用。实际就绪观察为 `MANAGED_APPLICATION_READY`，同一宿主请求读回原结果。管理用原键 `RECONCILE_RUNTIME` 登记成功，四项预留继续归原运行。
- 管理受理 `STOP`，真实 `stop-runtime` 正常排空并退出，同键读回原停止回执，原 STOP 对应四项释放。集成站控制 `CLOSED/NORMAL_STOP`、稳定锁无人持有、套接字消失。开发站的安装、控制、库、锁身份及原字节全程保持。测试未产生新的 Git 提交。
- 来宾 `r391-registry` 退出 0。实际管理库和 CLI 完整路径通过，本次未从浏览器发起管理操作，也未启用云端或生产登记。
