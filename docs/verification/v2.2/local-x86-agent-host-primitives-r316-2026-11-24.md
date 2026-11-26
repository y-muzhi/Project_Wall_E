# V2.2 R316 x86_64 内部 Agent 宿主机制复核

2026-11-24（香港时间）。无网卡、无端口映射的本机 Ubuntu 24.04.5 x86_64 临时来宾。Linux 6.8.0-147、glibc 2.39、ext4、cgroup v2。依据 V2.01 后端 7.11.7、7.11.8—7.11.10，仅使用两个独立假角色和临时 unit。

- 在来宾内临时固定非管道 `core_pattern`。真实受管假进程的 `LimitCORE` 软硬限制和 `memory.swap.max` 均为 0，`NoNewPrivs` 生效，有效能力为空，网络命名空间独立。用已固定的 PIDFD 令该测试进程故障退出，未在测试转储目录生成文件。退出后恢复来宾原 `core_pattern`。
- `busctl` 命令不支持传入 UNIX FD 参数。换用同一系统的 libsystemd 后，非 root 独立观察身份通过 `GetUnitByPIDFD` 得到该实际 unit 对象路径，传入普通文件描述符被拒绝。工具用法参照 [systemd sd_bus_call_method 文档](https://www.freedesktop.org/software/systemd/man/259/sd_bus_call_method.html)。
- L0 仍未整体准入。此来宾仅确认 AppArmor 模块已启用，缺少针对实际 OpenCode 的有效 profile、固定 Docker／runsc 和完整受管策略。未启动实际内部 Agent、工具容器或凭据链，原 ARM64 宿主的管道转储结论保留。普通及固定候选链不依赖 L0。
