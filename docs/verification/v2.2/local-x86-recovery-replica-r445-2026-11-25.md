# R445 实际 Linux 恢复副本发布

2026-11-25，独立开发工作区 `codex/2.2`。验证输入为当前开发工作树中 `backup_capture.py` SHA256 `3252c9efbe37d566cea5fe848ad028054e24bd50fcc180b757f5e9354dab2aaf` 与 `environment_recovery_installation.py` SHA256 `e6e72995403b416eb7a9a94a458498f08bd168a889067154d8e00986964ea182`，两项在 Ubuntu 来宾执行前比对一致。来宾为 Ubuntu 24.04.5 x86_64，固定 CPython 3.13.18、SQLite 3.54.1、31 个 wheel 和 19 个宿主库；运行包 SHA256 `0241128f2faa82bcc1f34d3f87196b0b817333caec2d070bf5a91f0cd3998e9e`。QEMU WHPX 进程 PID 49312 使用独立写时覆盖盘、无网络适配器、无端口转发，最后正常关机。

- 使用实际固定 Linux 普通安装入口建立新环境，生成 SQLite 捕获、恢复新代次及维护关闭控制；固定入口读取真实项目源码、SQLite 文件与恢复资产。
- `prepare_recovery_replica` 对真实捕获／恢复文件完成新目标副本发布。真实 Linux flock 在发布期间阻止宿主冻结，返回 `BUSY`；同一原计划重试读回相同回执，目标 SQLite inode 与源不同而摘要匹配。
- 暂存完成后先冻结宿主，正式副本发布按 `HOST_RECOVERY_HOLD` 拒绝，未生成最终目标，暂存清空。原宿主冻结后，独立封存包演练仍成功，源控制、数据库及归档成员身份和摘要未变。
- 这是固定批准输入处的原生锁／文件发布验证。恢复批准回调使用受控回执夹具；真实管理登记到正式候选入口、正式候选封存、ARM64、COS 及生产接入不在本次证据范围。

本轮另外一次完整普通服务闭环在 TCG 下停于 ASGI startup，验证夹具清理了其进程；缩减后若因遗漏服务定义失败也已修正。上述失败不作为通过证据。最终 WHPX 复验通过。R442 实际受管 SQLite 捕获、原登记派发和冻结后同键读回见 [R441／R442 记录](local-backup-dispatch-replica-r441-r442-2026-11-25.md)。

本轮临时来宾及输出位于独立 scratch `output/.v22-session-r445`，测试进程已正常退出；原有其他临时目录未触碰。未调用模型／计数服务，未连接或改动 8001 用户服务，未写入正常业务库，未创建 Git 提交或固定发布包。
