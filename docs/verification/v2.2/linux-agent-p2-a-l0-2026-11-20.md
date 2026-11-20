# WALL-E V2.2 内部 Agent 原型现场核对

2026-11-20（Asia/Hong_Kong）。专用 Ubuntu 24.04 ARM64 验证机，以当前普通验证身份只读核对。依据 V2.01 后端 7.11.7 L0、7.11.8—7.11.10、8.2 P2-a。

- 实际内核 `6.8.0-147-generic`、glibc 2.39、systemd `255.4-1ubuntu8.18`、cgroup v2。AppArmor 模块启用。通过 `busctl introspect` 看到 `GetUnitByPIDFD` 的接口声明，实际受限身份查询和原进程单位的绑定尚未验证。
- `/proc/sys/kernel/core_pattern` 实际为管道模式。本机尚未证明收集器会在读取秘密内存前排除这些进程，当前宿主不满足后端 7.11.10 的退出条件。Docker 和 runsc 不在验证身份的固定命令路径，也没有本轮已核实的平台包或策略模板。
- 结论为 L0 未准入。未启动带凭据的 L2/L3 夹具、OpenCode 或固定工具链；未更改系统转储、AppArmor/UID、加载内核策略或安装宿主软件。A3 普通环境的锁证据保持原范围。此结果未阻断普通 Linux 文档环境。继续接执行候选前需要独立满足转储、有效策略及受信程序身份的安装证明。
