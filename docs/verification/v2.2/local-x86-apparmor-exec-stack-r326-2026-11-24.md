# V2.2 R326 AppArmor 固定执行转换

2026-11-24（香港时间）。无网卡 Ubuntu 24.04.5 x86_64 派生来宾，Linux 6.8.0-147-generic。依据 V2.01 后端 7.11.10、8.2 P2-a，仅用两个短命原生程序、一个非 root UID、两个来宾临时 enforce 策略。测试进程没有有效能力，保持 `NoNewPrivileges=yes`、私有网络、零 core、零 swap。[AppArmor 叠加机制](https://gitlab.com/apparmor/apparmor/-/wikis/AppArmorStacking)。

- 固定启动程序在 bootstrap enforce 下读取普通夹具，观察者在转换前持有实际 pidfd。触发一次明确的目标 `execve`。进程身份、systemd 主 PID 及 pidfd 保持，实际程序文件切换到固定运行目标。
- 实际内核标签由单层 enforce 变成 bootstrap 与 runtime 的双层 enforce，`PR_GET_NO_NEW_PRIVS` 及进程状态仍为 1。运行态无法再读启动夹具，也不能执行第二个只用于检测的程序，两项均收到 `EACCES`。已核对完整标签，不只检查 unit 文本。
- 成功返回并停止原单元后，卸载运行层，使用同一个启动程序和已持有的启动策略重跑。固定转换返回拒绝，未能运行目标程序或生成运行态记录。两次临时运行及策略在退出前清理，未保留原始输出。

该原型验证固定执行转换、持续 NNP 和缺失策略无回退。未执行实际 Agent 二进制、私有端点、受限单向 proc 读取、真实权限秘密交付、gVisor 及联合准入。x86_64 原型证据不替代后续 ARM64。
