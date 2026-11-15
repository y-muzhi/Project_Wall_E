# V2.0 Windows LPAC 启动属性预检

2026-11-08（Asia/Hong_Kong），Windows x64、隔离 SQLite 3.54.1、db20-r29。

- windows_job.py 在同一原生属性列表中保留原 Job 和标准流白名单，可按受管配置名称派生实际包 SID，以零附加能力安装 SECURITY_CAPABILITIES 并显式安装 ALL_APPLICATION_PACKAGES_OPT_OUT。拒绝后不会交出可用于普通 AppContainer 的属性列表。属性及 SID 内存随原列表清理。 [Microsoft LPAC 启动契约](https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer)
- 原 START.CHECK_CONDITIONS 调用实际 Windows API，报告 lpac_creation_attributes_available。预检 Job 无任何进程；失败仍可查原 202 和真实阻断。已有不含该字段的回执可读。通过预检时仍须核对实际挂起令牌、只读访问、WFP、实例和完整停止。
- test_v20_windows_job.py、test_v20_windows_process.py、test_task_start_conditions.py 共 39 项通过，86.58 秒。覆盖实际 LPAC 属性安装、拒绝 opt-out 时不降级、无进程的临时 Job、已有原子挂起和子进程回收，以及原 START 成功收件后保留阻断。应用 Ruff 274 文件格式及改动文件 lint 通过。
- 未创建 AppContainer 配置、启动 LPAC 实例、改变 ACL／WFP 或运行 OpenCode。实际 LPAC 令牌和访问／网络／停止证据仍待取得。
