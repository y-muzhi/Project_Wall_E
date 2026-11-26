# R336 内部 Agent 启动端点原型未准入

2026-11-24（香港时间）。独立 `codex/2.2`，本机 Ubuntu 24.04.5 x86_64 无网卡来宾，Linux 6.8.0-147。依据 V2.01 后端 7.11.10 和 8.2 P2-a，使用两个专属非 root 假角色、独立强制 AppArmor 配置、同一私有网络、独立的挂载视图、零有效 capability、NoNewPrivileges、LimitCORE 0 和 MemorySwapMax 0。运行中使用的启动数据为受保护的角色绑定和合成测试值。

- 默认路径与两个角色显式挂入同一个专属的 pathname SEQPACKET 目录均已实跑。后者从两个进程实际根核对目录设备和 inode 相同，网络命名空间相同，挂载命名空间不同。AppArmor 在启动器 `connect` 时以 `EACCES` 拒绝，内核审计原因为 `Failed name lookup - disconnected path`。
- 控制端未接受握手，启动器未进入运行态。拒绝后检查 GRANT 的派发记录、结果记录和运行记录均不存在。两类测试秘密没有被生成、发送或写入。未用 AppArmor 路径回接标志、更宽策略或共享挂载空间使候选继续。
- `python run-guest.py r336c-secret disk-r323-runtime.qcow2 offline 200` 成功确认拒绝及清理。原启动候选仍为未准入，适用 `EXECUTION_DEPLOYMENT_NOT_ADMITTED`。只有来宾的非管道转储设置被临时更改，结束时已恢复并移除专属策略、单元，无转储文件。

已单独通过的原 pidfd、D-Bus、AppArmor 执行转换和私有 TCP 接受检查继续各自有效。此候选的双向系统总线认证、GRANT／RECEIVED、原进程执行、错误过滤和固定 OpenCode 仍未执行。接续须另证明确切端点与强制路径策略兼容并保留独立挂载边界。[systemd 执行环境规范](https://github.com/systemd/systemd/blob/v255/man/systemd.exec.xml)
