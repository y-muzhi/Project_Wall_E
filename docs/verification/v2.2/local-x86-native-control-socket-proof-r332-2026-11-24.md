# R332 私有回环的实际接受方证明

2026-11-24（香港时间）。独立 `codex/2.2`，本机 Ubuntu 24.04.5 x86_64 无网卡来宾。测试使用固定静态 C 假角色。控制端建立 systemd 私有网络，目标通过 `JoinsNamespaceOf` 共享实际网络对象，两个角色同 UID、不同 AppArmor enforce 策略和不同挂载视图，分别具有各自的 `/tmp`。只有 lo，IPv4／IPv6 无默认路由，来宾默认网络空间无法连接 4096，宿主无端口映射。两端均无有效 capability 并保持无新权限。

- 正向使用真实 `NETLINK_SOCK_DIAG` 完整核对 IPv4／IPv6 监听集合、驱动回复来源和序列。控制只保留一条原 TCP 连接和原目标 pidfd。目标故意延迟接受，建立 TCP 后控制先看到等待，目标接受时实际接收队列为零。控制核对服务端四元组、cookie、UID、inode 与原目标 proc FD 链接，重核后才在同一连接发送一个无业务含义的字节。应答后重复核对原连接和进程仍有效。
- 否定场景在同一个私有网络加入第二个同 UID、不同 enforce 角色的实际监听者。控制枚举同一端点的两个监听，在建立连接前拒绝。目标与第二监听者全程均未收到连接。
- 当前由夹具从实际 systemd 主进程、程序和调用身份安装目标身份。未实现正式的 GetUnitByPIDFD 联合核验、完整原任期、固定 OpenCode、实际模型或工具场景。未采用调试 capability 或更宽的共享网络策略。

执行 `python run-guest.py r332c-sock disk-r323-runtime.qcow2 offline 175`。两个场景、专属单元和策略清理通过，来宾退出 0。早期夹具以短于目标负向观察期的期限读取日志，延长夹具观察后通过，未修改隔离层。核对资料。[Linux socket 诊断](https://man7.org/linux/man-pages/man7/sock_diag.7.html) · [systemd 单元的命名空间关联](https://github.com/systemd/systemd/blob/v255/man/systemd.unit.xml)
