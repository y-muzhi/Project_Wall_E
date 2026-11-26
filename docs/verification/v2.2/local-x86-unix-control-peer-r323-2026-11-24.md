# V2.2 R323 Linux 控制连接内核原型

2026-11-24（香港时间）。独立 `codex/2.2` 的无网卡 Ubuntu 24.04.5 x86_64 临时来宾，Linux 6.8.0-147-generic，Canonical 输入镜像和 QEMU 11.1.3 文件均核对。仅使用专属非 root UID、自己创建的路径型 AF_UNIX／SOCK_SEQPACKET 和测试子进程，无业务库、真实 Agent、来源秘密或供应方。依据 V2.01 后端 7.11.7、8.2；[Linux Unix 套接字机制](https://man7.org/linux/man-pages/man7/unix.7.html)。

- 启用并核对 listener 与接收端的 `SO_PASSCRED`。客户端在 accept 之前排入第一报文，实际 `SO_PEERPIDFD`、`SO_PEERCRED` 及逐消息 `SCM_CREDENTIALS` 匹配原进程，保有不可继承的 pidfd。核对真实程序文件身份与 PID／user／mount 命名空间。两个正常消息保留独立边界。
- 同一个非 root UID 下，继承原连接的另一个测试进程发送第二条消息时未得到原连接资格。关闭接收凭据的反例也被拒绝。超 64 KiB 报文、截断辅助数据及未授权 FD 被拒绝；实际 `MSG_CMSG_CLOEXEC` 生效，并在所有报文结束后比对进程 FD 清单，未遗留收到的副本。
- 客户端关闭连接但仍活时，接收端实际读到 EOF，原 pidfd 仍未报告退出。原客户端退出后，已持有的 pidfd 才产生退出事件。该观察可供后续区分断连和进程退出。
- 七个内核场景通过，自有子进程、描述符和 Unix 路径在原回收边界释放。虚拟机无主机端口映射。

尚须验证实际控制请求的固定应用字段、原任期处理、允许的唯一 ATTACH pidfd 语义、单向 proc 与 NNP 执行转换、实际 OpenCode／runsc 联合准入和目标 ARM64，不以本记录准入完整内部 Agent。
