# V2.0 Windows 网络过滤层只读预检

2026-11-08（Asia/Hong_Kong），Windows x64／SQLite 3.54.1／db20-r29。范围为 BE 7.3.2 的本机 WFP 只读能力与原 START.CHECK_CONDITIONS。

- 以固定 Windows SDK GUID 在同一只读事务中核对 IPv4／IPv6 的 ALE 连接、监听和接收层，并检查各层必要的包 SID、地址和端口条件。只读事务结束后关闭原会话；发生关闭失败时保留原所有者供核对。START 单独记录 wfp_local_ale_layers_readable，可读取不含该项的旧回执。 [Windows SDK](https://github.com/microsoft/win32metadata/blob/main/generation/WinSDK/RecompiledIdlHeaders/um/fwpmu.h) [微软只读事务](https://learn.microsoft.com/en-us/windows/win32/api/fwpmu/nf-fwpmu-fwpmtransactionbegin0)
- 本机实际观察。受限进程打开 WFP 引擎时返回 Windows 错误 5。隔离测试的普通用户可打开引擎，但开启只读事务返回 5。独立逐层只读调用也均返回 5。没有把错误 5 解释为层缺失或策略已经生效，也没有修改 WFP 读取权限。
- Windows WFP 单文件专项 9 通过（0.09 秒）。固定 SQLite 下 WFP、Job、START 检查组合 32 通过（77.77 秒）；应用 Ruff 275 文件格式、改动 lint 及 Git 空白检查通过。
- 隔离夹具覆盖六层／字段、无重复原层、打开／开始／读取／结束失败、分配释放和原句柄关闭异常。正向系统读回、Guard 实际规则安装、优先级与仲裁、真实允许／拒绝连接及完整停止回收仍待。未改用户网络规则、未启动正式服务或 OpenCode。
