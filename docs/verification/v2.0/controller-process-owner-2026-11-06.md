# 原控制方进程句柄独立寿命（2026-11-06）

目标：Guard控制方owner不能长期借随管道连接关闭的peer._process；按[通信细化](../../iterations/pending/v2.0/WALL-E.Guard本机通信实施细化_V_2.0.md)从实际已经持有的原句柄取得独立副本，不重开旧PID。

windows_process.ObservedProcess.duplicate()：先验证原对象，DUPLICATE_SAME_ACCESS、不可继承、同进程目标，保持原只读QUERY／SYNCHRONIZE权限；原PID／creation-time核对，源关闭后副本独立存在。复制失败不动源；验证后清理失败保留确切新owner，重试仅原句柄。先在内存建立owner再分配OS句柄，源码同目录temp／fsync／原字节复核／os.replace。

## 当前检查

- 已保存test_v20_windows_process.py三个新增用例及test_v20_windows_pipe_peer.py一个原管道关闭后原普通token／同进程退出用例。
- 不要求普通令牌的当前只读对象专项（标准受限环境）3通过、1既有Starlette弃用警告，1.05秒。没有以此替普通用户管道／ControllerPrimaryToken专项。
- 普通非提升隔离三文件专项两次被自动审批服务403拒绝启动：review服务未能完成，非不安全判断，没有绕过；该范围**未执行**，待连接恢复。最后当前代码223 app文件Ruff格式、windows_process.py lint及git diff --check通过。
- 当前没有活动检查；没有安装服务、修改正常库／既有ACL／网络或真实调用。此前窄恢复22文件413通过在本方法加入之前，不能充作本次普通peer新结果。

下一步接独立GuardControllerOwner：原程序准入及私有登记先确认，原Native句柄副本＋PrimaryToken＋Registry watch不随连接释放；只有全域封闭／原资源无活动后，才关闭watch、token及原副本。所有长期TypedCommand／文件／程序租约保持原actor线程；准备完整七动作及仓库生产全链。

## 后续实际回归

普通审批随后恢复，原peer／token／副本和新增实际owner链路已随22文件395通过83.22秒；见[owner记录](guard-controller-owner-2026-11-06.md)。当前无审批阻塞，原未执行记录保留为当时状态，不再列当前缺口。
