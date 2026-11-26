# R492 当前固定程序的便携备份和私有恢复

2026-11-26。无网 Ubuntu x86_64 QEMU 来宾，当前固定程序 `693c74ba14a8d4b3b02dd50aeb7c3b72cb8379a5bb2f5ffd090323468f0b93b4`，V2.2 Schema 对象摘要 `ed057e0ddadbcdbb47bd8e78c541cf009fd719c397ffe79579d3ae2684802fc3`。业务进程、维护流程和恢复副本各使用指定 Linux 用户、独立目录、库、锁和 Unix 套接字。

- 实际普通应用创建需求、文档并完成编辑。受原稳定锁保护进入维护。原命令 `capture-database`、`check-backup-coverage`、`restore-database`、`seal-result-index`、`check-recovery-chain`、`seal-backup-package` 生成可移动包和 5 条原结果索引。
- 把包复制到独立受保护目录，逐文件核对不同 inode 和相同摘要。实际 `verify-backup-package`、`lookup-backup-result`、`rehearse-backup-package` 通过，保留原请求 HTTP 状态。演练新代次、原环境 UUID、正文和 SQLite 完整性通过独立只读核对。包 `b90453eaf31f57551d5fe234e931f74efc81a6e6af3cbdd77ca8a283ffa44366` 对应最终未加诊断的来宾复验，早一次独立包 `8701834ebbb1783c5b91532c9a9da1a2005a7ab64ba999d67e6af4eec73a6c9f` 同样核验通过。原库、原控制、原捕获 SHA256 和封包清单保持。
- 实际 `prepare-recovery-replica` 完成私有安装，使用新代次和固定前端。随后 `verify-recovery-replica` 一次返回 `RECOVERY_APPLICATION_START_TIMED_OUT`，减少并行后一次返回 `RECOVERY_APPLICATION_STOP_UNVERIFIED`，均未出具通过回执。产品超时、锁和退出条件保持。当前在新来宾保留实际运行入口，仅增加子进程诊断观察。
- 早期夹具没有为维护关闭后的直接还原提供原维护引用，固定入口正确拒绝。补入精确引用后恢复通过。另一次业务样本在并行来宾下遇到夹具 HTTP 超时，增加夹具等待后重试。每次结束均清理本轮进程和临时覆盖盘。

当前已验证实际备份、搬移、新代次演练及私有安装准备。当前工件的私有应用启动／回收实证、正式恢复安装和对外入口联验暂未验收。

## 子进程诊断

随后用同一产品验证入口在新来宾复验。同一工作树和 Schema 重新生成包 `28ced83ac75129ca5843dc596d48e4f0184fdc5dc9b3d65315d9e3b5e49332f1`，5 条原结果、搬移、演练和私有安装准备再次通过。诊断只记录实际子进程输出、运行状态、套接字和稳定锁观察，不改变命令、身份、等待上限或退出规则。

实际等待 35.01 秒返回 `RECOVERY_APPLICATION_START_TIMED_OUT`。子进程仍运行，但业务套接字与稳定锁持有者均未出现。产品发出 SIGTERM 后约 0.04 秒退出，退出值 −15。当时应用尚未进入可观测就绪，未出具 `LOCAL_VERIFIED` 回执。该次诊断未能定位具体耗时函数。来宾退出并清理本轮覆盖盘。宿主单独以无磁盘、无网卡、暂停 CPU 的进程复查 WHPX，返回 `hr=80070005`，未取得硬件加速。后续需在有当前固定运行包的原生或加速 Linux 环境，用未放宽的验证入口追踪启动预检阶段。

## Windows 定向核对

用两个隔离工作区各自的锁定依赖，分别运行 `python -B -m pytest backend/tests/infrastructure/test_v22_startup_preflight.py::test_ordinary_preflight_entry_checks_ownership_before_inspecting_database -q -p no:cacheprovider`，各 1 项通过。普通预检未持有稳定锁时拒绝读 SQLite。包含异步生命周期的初次组合命令未产出结果，已终止两个本轮会话。同步测试与 Linux 私有应用的启动证明分别记录。
