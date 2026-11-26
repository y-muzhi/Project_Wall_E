# R331 实际 systemd 宿主停机回执

2026-11-24（香港时间）。独立 `codex/2.2`。Ubuntu 24.04.5 x86_64 无网卡来宾，从 R325 已初始化并正常关闭的集成环境复制测试。固定 Python 3.13.18、SQLite 3.54.1、普通程序和两个环境源均有原身份。

- 使用现有 `startup_command` 生成专属 transient unit。采用实际 cgroup、稳定锁、独立 Unix 套接字、两进程和应用就绪核验，`runtime_result` 两次返回 `MANAGED_APPLICATION_READY`。
- 实际 `stop_runtime` 调用 systemd 正常停止。控制到修订 13、`CLOSED/NORMAL_STOP`，原键返回完全相同的 `STOPPED` 回执，回执 inode 和内容保持，异键返回 `MANAGEMENT_OPERATION_CONFLICT`。
- 独立第二次运行期间，以应用 UID 保持原 SQLite 读事务，真实业务 API 提交一个测试需求。检查点忙后，停机返回 `MANAGEMENT_STOP_EFFECT_UNVERIFIED`，宿主观察为 `UNKNOWN`，控制仍在修订 16、`DRAINING`。解除读事务后按原键再次观察，仍保留原 `DISPATCHING` 的 inode 和字节，异键被拒绝。该测试需求只写一次且可读，SQLite 完整性通过，开发环境的安装、控制和数据库摘要保持。

执行 `python run-guest.py r331b-managed disk-r325d-ordinary.qcow2 offline 200`，来宾退出 0。准备过程中修正夹具的非 root 用户参数与测试标题长度。实际启停只涉及来宾内两个指定 systemd 单元，结束时无残留 cgroup 和应用套接字。采用宿主原入口和真实普通应用。完整管理登记事务和四项容量另测。
