# Guard原资源登记／控制方退出及宿主崩溃（2026-11-05）

- 代码：V1.5基线28a7c9e后的V2未提交实现；runtime_control_git.py接原LaunchJournal、ControllerPrimaryToken、SuspendedControlGit及原IO／pin／Job。当前仅固定Git --version，不是Guard服务／Pipe入口或完整Git命令。
- 输入／不变量：一个真实原控制方token及controller_ref；每个原scope绑定原program／directory／Job／STDIO，注册新绑定要求空原Job。登记先于Native创建，原scope同输入复用、不同原对象拒绝；重启缺RAM资源不得据磁盘记录重建进程或重新打开PID。最多128域／10万私有记录，容量不足保持未知，不删除已有证据。
- 私有OS回执：原Guard进程身份／guard_run_ref、原scope、程序及目录身份、原token输入SHA、Job不透明ref、STDIO不透明binding、原Root身份／resource_ref及实际观察；不含原始OS句柄、业务正文／状态或凭据。同目录临时写入、fsync、MoveFileEx WRITE_THROUGH且禁止覆盖、成员ACL及SHA／确定JSON读回；同一观察只读核对原回执，不不断写重复文件。回执只能读取证据，不能成为执行输入。
- 实际调用链：register→原journal CREATE MAY→真实AsUser挂起→RAM保留原Root→原身份回执发布／读回→原journal RESOURCE_RECORDED；恢复同样在原journal RESUME MAY后单次Resume，原ACK记录失败仍保留原Root及MAY，不重发。
- 停止：原域入口先设置独立stop_requested内存屏障，再持久封闭原nonce并终止所属Job。发现持久封闭在写入前失败也须禁止迟到create／resume，已补并专项覆盖；回执或封闭失败不妨碍向已知原Job请求终止，但不报告已停止。
- 控制方watch：只观察原held process，退出或观察不可用都关闭新准入并封闭／终止原scope；逐域非阻塞取锁，一个忙域不挡其他域。所有原域封闭且原Job／Root已核清后才允许停止watch。Native句柄释放与调用方Job／IO／pin／token／ACL完整清理分开，不写Task终态。

## 实际检查

获准普通非提升环境、固定SQLite启动器＋quality_python、自有临时根：
- test_v20_runtime_control_git.py／test_v20_runtime_launch_journal.py／test_v20_windows_native_process.py：**51通过，53.70秒，无正向跳过**。使用真实私有包模式；覆盖原绑定／回执、创建／恢复记录丢失、容量／篡改、无PID停止、持久停止失败的内存屏障、观察失败回收、真实控制方退出回收、忙域不阻塞及无RAM原资源拒绝。
- test_v20_runtime_guard_crash.py：**1通过，3.95秒**。自有普通Guard测试宿主运行实际生产Registry／AsUser，原控制方保持活着；固定Git仍挂起。父测试先持原process身份句柄，精确终止原Guard worker，外层测试Job保持打开且尚未请求终止，原Git随Guard独占内层Job最后句柄关闭实际退出。随后重开原私有journal，原nonce已封闭且保留原resource_ref；CREATE／RESUME回调均未触发。
- 169个生产Python文件Ruff format、runtime_control_git.py的Ruff check及git diff --check通过。既有Starlette httpx弃用提示保留。

初始单文件执行缺peer夹具导致10个setup错误（未创建Native进程），已补完整依赖；后续两次各1项断言错误分别是同控制方未登记scope的UNKNOWN、停止后返回原CLOSED事实的合法行为，已按契约校正并核对无新进程。上述最终51项才为完整组合通过。报告不保留原始JSON／日志；测试所有私有回执、宿主及Git临时对象已清理。

## 边界

当前没有安装／启动SYSTEM服务，没有受保护运行包或真实Pipe程序认证；宿主崩溃证明仅针对自有普通进程中这条实际原生链路，不能扩大为部署Guard／LPAC／WFP／完整Task停止／产品验收。Registry只释放自身原Root句柄，外层仍负责所属Job／IO／pin／ACL最终清理。未授权真实模型／计数、正常仓库／库或用户服务操作，均未执行。runtime_admitted仍false。

Job／CreateProcessAsUser／最后句柄回收的一手依据及先前原语检查见[Job记录](native-job-ownership-2026-11-05.md)和[AsUser记录](native-as-user-launch-2026-11-05.md)。
