# R356 独立启动观察者的系统总线实际边界

2026-11-24（香港时间），独立 `codex/2.2`，本机无网卡 Ubuntu 24.04.5 x86_64，systemd 255 与强制 AppArmor。运行的文件、命名空间、用户、角色、unit 和证据均为合成夹具。

- 第一轮短期观察者采用 systemd 私有网络装配，仍因挂载视图中 pathname 断开，无法连接系统总线。
- 第二轮在来宾内预建专属命名网络。单独受信前置程序仅进入该网络，沿原宿主挂载视图启动观察者，在执行前降到独立非 root UID、移除全部能力并要求 NNP 和强制角色。待查角色继续保持独立挂载。观察者以该角色接收真实 Unix peer 的 PIDFD、UID 和强制标签，能连接实际系统总线。D-Bus AppArmor 在 `GetUnitByPIDFD` 的精确方法调用处拒绝，审计返回 `org.freedesktop.DBus.Error.AccessDenied`。没有取得目标单元或任期回执。
- 针对额外显式系统管理器标签的策略试验被自动审批拒绝，理由是可能扩大 AppArmor 的对端匹配。该试验未运行，没有改变实际策略。准备的替代观察者没有接入 WALL-E 产品。
- 两轮均安全退出，收回专属测试 unit 与策略，命名网络只在第二个来宾创建，随本轮来宾和临时覆盖盘清理。没有假凭据交付、固定 OpenCode、模型、计数或业务访问。完整内部 Agent 继续按 `EXECUTION_DEPLOYMENT_NOT_ADMITTED` 阻断。
