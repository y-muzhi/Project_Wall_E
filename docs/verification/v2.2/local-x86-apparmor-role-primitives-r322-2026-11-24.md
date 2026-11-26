# V2.2 R322 Ubuntu AppArmor 假角色分离

2026-11-24（香港时间）。独立 `codex/2.2` 的隔离宿主原型工作。无网卡 Ubuntu 24.04.5 x86_64 来宾，无宿主端口映射。使用同一专属非 root Unix 用户、同一读取二进制、同一普通可读测试文件和两个仅存在于来宾的临时配置。没有产品数据库或真实 Agent 工具。PIDFD、core 和 cgroup 机制的另一个隔离证据见 [R316](local-x86-agent-host-primitives-r316-2026-11-24.md)。

- 用 `apparmor_parser -K -a` 装载两个小策略，内核列表记录两者均为 `enforce`。同一测试 UID 在无这两套角色的权限基线下读到文件，核对普通 Unix 文件权限相等。
- 用 `systemd-run` 为两个单元明确配置不同 `AppArmorProfile`，均使用同一个 `User`、独立网络、禁止新权限、零 core、零 swap。两次运行同一个原生读取程序。它只通过退出值报告实际文件读取或 `open(2)` 的 `EACCES`。
- `systemctl show` 实际观察到控制单元 `Result=success, ExecMainStatus=0`，受限假 Agent 单元 `Result=exit-code, ExecMainStatus=13`。早期夹具因 stdout 继承和启动包装器退出值未区分而未过，最终采用同一二进制直接返回关键事实，读取 systemd 真实主进程状态。
- 两个临时单元停止后卸载两份策略，内核已无所创建的 profile，来宾正常退出。未保留原日志或配置。

覆盖 AppArmor 在指定本机上的强制加载和同 UID 下的角色边界。实际生产角色全量策略、固定 Docker／runsc／OpenCode、私有资源和进程联动、ARM64 与 L0 联合准入继续待验。普通开发和集成的启动条件不包括内部 Agent。
