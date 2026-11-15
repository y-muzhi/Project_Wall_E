# V2.0 LPAC 启动属性预检

2026-11-08，BE 7.3.1—7.3.3 实施细化。

Guard 使用既有原生 Job 启动属性列表。添加 LPAC 时，Windows 派生该私有配置名称的包 SID，以零附加能力设置 SECURITY_CAPABILITIES，并用 ALL_APPLICATION_PACKAGES_POLICY 显式选择 OPT_OUT。任一属性失败均中止；同一原子 Job 关联、独立标准流允许列表照常适用。 [Microsoft LPAC 启动契约](https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer)

START.CHECK_CONDITIONS 在 Windows 上执行无副作用的属性预检。测试身份名称使用独立随机值，只有 SID 推导及内存属性安装，且复核 Job 内没有分配进程。此证据只表示当前 Win32 API 能构造规定的属性；未创建配置、启动进程或改 ACL／网络策略。实际挂起令牌、任务文件权限、网络仲裁及停止释放仍单独验证，缺失时禁止派发。 [Microsoft SID 推导](https://learn.microsoft.com/en-us/windows/win32/api/userenv/nf-userenv-deriveappcontainersidfromappcontainername)
