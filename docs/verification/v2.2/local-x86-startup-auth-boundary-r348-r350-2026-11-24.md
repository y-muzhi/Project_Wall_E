# R348／R350 Linux Agent 启动通信与系统总线边界

2026-11-24（香港时间），独立 `codex/2.2`，本机无网卡 Ubuntu 24.04.5 x86_64，Linux 6.8.0-147、systemd 255、实际强制 AppArmor。依据 V2.01 后端 7.11.10 与 8.2 P2-a。试验仅使用本机临时进程和固定测试报文，无真实 Agent、模型、计数或用户数据。

- R348 在同一个私有网络、不同挂载命名空间下运行两个同 UID 假角色。两端精确抽象 SEQPACKET 地址、AppArmor 对端标签和原活 PIDFD 均实际核对；逐报文凭据和一字节固定标记通过。独立的同 UID、同网络错误角色在监听器启动前绑定失败，能绑定自己被许可的地址但仍被正确监听端拒绝。相同正确角色放在另一个私网时无法连接原端点。无通配的 Unix SEQPACKET 权限。测试结束删除专属单元和配置。首次机制全部完成但主机等待关机超时；以同一夹具及延长关机等待复验，`r348a-abstract` 正常退出 0。
- R350 从这个端点继续尝试两端直接向 systemd 查证实际原任期。默认 `sd_bus_open_system` 在独立强制策略下先尝试绑定额外的内部 abstract stream 地址并被拒。第二次以已指定的系统总线路径和 `sd_bus_set_fd` 连接，两个角色均收到 pathname 的 `Failed name lookup - disconnected path (EACCES)`，在 `GetUnitByPIDFD` 前停止。
- R350 依检查约定退出。没有生成或发送任何 GRANT，也没有启动固定目标程序。保留独立挂载、NNP 和固定强制策略。原 R336 的 pathname 候选和 R350 的直接总线候选均维持未准入，R348 仅证明启动报文的本机内核机制。 [AppArmor Ubuntu 规则](https://manpages.ubuntu.com/manpages/noble/man5/apparmor.d.5.html) [systemd fd 接口](https://www.freedesktop.org/software/systemd/man/254/sd_bus_set_fd.html)
