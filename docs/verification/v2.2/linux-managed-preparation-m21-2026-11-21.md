# V2.2 M21 独立准备服务及原启动接续

2026-11-21（香港时间）。Ubuntu 24.04 ARM64、systemd、cgroup v2、固定 r3 运行包。实际程序为 `program-m21-51c0b3ec4e7e`，SHA256 `f15d084282066b200da3a4495c6b73cbd41702666849e95ae39aed5fb4a98015`。依据 [V2.2 准备过程](../../iterations/pending/v2.2/WALL-E.受管普通启动的准备进程_V_2.2.md) 和 V2.01 后端 4.6、4.8、7.9。专项经固定 `manage_registry.py` 的 `start-runtime`、`cancel-runtime`、`stop-runtime` 及原 `operation` 入口执行，格式检查为 `python -m ruff format --no-cache --check backend/app`。

- 先验证真实的单次 systemd 服务。直接指定未登记的数字 UID 时得到 `217/USER`，无归属进程，已按单元名和 InvocationID 清除本轮失败记录。专用无登录账户成功。最终按本项目原数字维护身份契约，用固定 setpriv 只在切换时保留 SETUID／SETGID，取消附加组并限制提权；以实际进程身份及退出证据核对。
- 实际两套普通应用分别完成启停。宿主先为唯一原启动持久化 PREPARING 和准备派发记录，核实同一开机、命令绑定、InvocationID、原准备回执及空 cgroup；关闭精确退出的准备单元后启动应用。模拟调度已接收但返回丢失，使用原操作恢复了真实准备结果。另补验实际准备组已停止、RELEASED 写入中断，原 OBSERVED 的同一 InvocationID 可核对退出并补齐回执，未重启准备组或启用应用。另一反例在准备派发记录存在、单元及回执均无法核实时重复检查两次，原额度保持，未重建准备单元或应用单元。
- 本轮同一真实容量槽争用、等待后继续、已就绪实体原取消、正常停和重复原回执通过。后端应用树 Ruff 格式与受影响模块 F 检查通过。以同一固定程序对三套实际普通安装回归，覆盖 ABSENT／RESERVED、准备或应用证据不足保留额度、RUNNING_UNREADY、旧结果不影响新租约。实际管理 HTTPS 的只观察核对通过，独立 Firefox 读取容量、等待、未确认就绪、取消待核对与已关闭回执，未发起写命令。管理前端静态索引 SHA256 `f71f1d95c4e403ffa0a9c52fb2e4b9431f696a97fa457f030abc407ba45e0e27`。
- 确认 Linux 本轮准备／应用单元、临时策略、身份、专属套接字及 9443／9444 均已清理，四套持久测试安装保持 CLOSED。Windows 转发、私有 Firefox 配置和 23 份临时验证入口已清理。
- PREPARING 已派发后的取消仍按未核实保留。还需让维护身份在稳定锁下完成控制回退和精确准备实体的原取消，验证回退写入丢失返回、并发和容量释放。应用 OPEN 前进程身份不完整的分支另验。生产接入尚未执行。
