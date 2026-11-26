# V2.2 R319—R321 停写、固定程序与实际网关

2026-11-24（香港时间）。独立 `codex/2.2`，Ubuntu 24.04.5 x86_64、原生 ext4、固定 CPython 3.13.18／SQLite 3.54.1，无网卡来宾。普通业务 HTTPS 9443、管理 HTTPS 9444 仅在来宾回环，无宿主端口映射。

- 原隔离样本存在 0 字节 WAL 与 32768 字节 SHM。实际 `check-release-preflight` 返回 `BACKUP_COVERAGE_SOURCE_CHANGED`，主库、WAL、SHM、控制文件摘要前后一致。离线另验证非空 WAL 的最新记录可读、日志字节保全。
- 普通停止在完成 HTTP 排空且持有稳定锁时，使用 SQLite 的 `wal_checkpoint(TRUNCATE)`。只有归属、数据库绑定及侧文件消失均通过才记录 `NORMAL_STOP`。真实新开发环境使用物理 WAL 主库，正常停机后在维护捕获和预检前均无 WAL／SHM。无侧文件的锁内读取保持无侧文件。
- 新隔离样本完成浏览器、应用、备份恢复、构建四类证据，封存 `b83f6fc947928c0affe7b91a2166dfd4101a661c1e4255a8a54219ecf05ab8fe`。`candidate --require-release-evidence` 返回四类齐备。封存目标来自已存在的集成提交 `deacba8a9545122f35a2f85c125a354205e06461`，本轮未提交源码用作受信管理与核验工具。
- 实际开发环境维护关闭、稳定源捕获、5 条原结果、独立只读恢复、`check-release-preflight`、`select-release-deployment` 至修订 7 通过。原文件与数据代次保持，选择重试返回同一结果，外发冻结。观察者核对目标程序、独立 Schema 和应用 UID，以已有只读身份通过私有 Unix 套接字读回原正文。`verify-release-deployment` 为 `RELEASE_DEPLOYMENT_VERIFIED_CLOSED`，复验回执摘要 `cc4b1d017dda3dbbe34b5f71c11b1c331a2a5e2986ab4ebcf47aa70ecd875e2d`。
- 真实 Caddy 绑定指定入口，新旧静态资产、关闭站点的认证与 API、同一进程和配置复核均通过。`verify-release-gateway` 持久化 `RELEASE_GATEWAY_VERIFIED_CLOSED`，重读同一回执并检查控制未变，另一集成环境经 TLS 读回自己的正文。回执摘要 `6456c57508ab6b6d5e22c45c1e8413cae70f7ed9a3ada5da79b82f30112824f2`。最初续跑夹具引用了错误的组字段，修正后从原关闭态继续。
- `serve-release-open` 启动失败。封存旧程序在 `GuideWorker.start` 的 `preflight` 使用常规 SQLite 只读连接，固定目标在 `ReleaseOpenScope.before_recovery` 的无侧文件检查报错，未写入开放控制。当前工作区已改为持锁下无侧文件的只读访问。实际派生来宾再次核对原控制仍处于 `CLOSED/RECOVERY_REQUIRED`、修订 7、划定的外发冻结、无应用套接字。同一实际 SQLite 3.54.1 下，分别用旧包与现行源码的 `inspect_database` 在应用 UID 下检查各自 Schema 的新测试库，旧版产生 WAL 和 SHM，现行版两者均未产生。旧固定包与原日志保留至临时来宾按测试范围清理。要验证真正开放，必须经明确集成交付得到包含整改的新固定候选，再重新封存和实跑。
- 本轮 193 项后端及 16 个子项通过。682 个文件的固定 Ruff 格式、改动文件的 F／I、109 个变更 Python 文件的内存编译以及 `git diff --check` 通过。当前普通和管理前端通过类型、格式检查及固定构建，120＋3 个发布文件与先前固定构建逐文件一致。

环境侧的实际重新开放、受管发布补记、ARM64 平台、腾讯 COS 双宿主及正式用户服务继续待验。相关普通应用、Caddy、Chromium 与无网卡来宾已结束，原日志、浏览器资料、镜像与本轮专属临时目录已清理。
