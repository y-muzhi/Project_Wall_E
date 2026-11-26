# R330 x86_64 单向进程元数据原型

2026-11-24。独立 `codex/2.2` 工作区。原型在本机 Ubuntu 24.04.5 x86_64 虚拟机的无网卡环境运行，只有两个专属临时 systemd 服务和 AppArmor 策略。固定的 C 假角色以同一非 root UID 运行，实际无有效 capability，执行期间保持 `NoNewPrivileges=1`。控制进程禁止转储，目标允许执行限定的 proc 检查。

控制策略仅为目标策略授予 `ptrace(read)` 和对应 `readby`，两端均验证实际 enforce 标签。控制端读取目标原 FD 的链接与网络命名空间链接成功，直接打开目标夹具内容、经 proc 链接打开内容和读取目标环境变量均失败。目标端反向读取控制进程 FD 的链接及无副作用的同 UID 信号存在性探测均被拒绝。

执行 `python run-guest.py r330a-proc disk-r323-runtime.qcow2 offline 160`。第一次夹具编译缺少声明 `dup3` 的特性宏，补齐头部定义后原边界完整通过，虚拟机退出 0。两个角色和策略已在该次 guest 关机前清理。未运行正式 Agent、联合 HTTP 入口、实际工具或 ARM64 验收。
