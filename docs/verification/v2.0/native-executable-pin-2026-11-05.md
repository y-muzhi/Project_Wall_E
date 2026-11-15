# 固定程序原对象锁定与Schema r4验证（2026-11-05）

- 代码状态：V1.5基线28a7c9e之后未提交的V2实现；BE 0.17-draft-17／FE 0.16-draft-16，正式设计未修改。新增 infrastructure/windows_executable_pin.py 及对应专项；windows_local_paths.py.close保留实际未关闭句柄，半关闭状态禁止verify。
- 输入／输出／不变量：输入必须由受信程序目录提供本地路径、原字节数／SHA256及可选原FileIdentity，不能直接采用RPC自报路径／摘要。输出为原NTFS对象的只读非继承lease及固定win-x64观察；所有祖先禁止替换，数据句柄仅FILE_SHARE_READ，创建借用期间禁止关闭；任何未知或部分关闭保留原owner供原句柄清理。
- 实现：复用LocalPathGuard实际最终路径／卷／128位file ID／NTFS／硬链接与reparse拒绝；同步ReadFile按64KiB计数／SHA256，验证AMD64 PE32+ executable且非DLL；拒绝设备、目录、EFS、offline与recall属性。创建前后重新核对原字节和身份。无进程启动、目录ACL修改、签名或完整运行包准入结论。
- 原共享源码改变后另发布不可覆盖db20-r4，manifest SHA256 8fea2825d0bae93e59ee826d36b3813a73c9d1f26075ade064f574744746a795；r1—r3原字节保留。当前编译pin已指向r4，启动源摘要重新一致。

## 实际检查

- 固定SQLite启动器＋quality_python，普通非提升环境：test_v20_windows_local_paths.py／test_v20_windows_private_package.py **13通过、22子场景，0.43秒**。默认AC环境此前5通过／2失败：创建测试hardlink和junction被系统拒绝；不是实现放行。
- 普通非提升环境：test_v20_startup.py／test_v20_published_schema.py／test_v20_schema_release.py／test_v20_maintenance_flow.py **14通过，71.71秒**；实际新解释器默认200、原151拒绝、原文档／关闭HTTP、私有维护演练／提交／未知回执／新业务数据保留。已有Starlette的httpx弃用提示保留。
- 前一次默认AC组合170秒超时，测试结束尝试也超时，未记通过；随后经获准只读核对唯一测试标记无存活Python，精确自有临时根已清理，再在获准普通环境执行上述14项成功。
- 默认环境：test_v20_windows_executable_pin.py **34通过，1.57秒**。真实固定MinGit cmd/git.exe与已发布inventory匹配但未执行；其余均自有临时文件。覆盖非继承／分块原字节、已有writer拒绝、文件与祖先替换拒绝、同字节新对象拒绝、PE／限额／摘要／属性错误、读取失败、借用关闭、数据及祖先关闭失败保留。
- 所有报告仅此Markdown；测试原始输出内存捕获，专属临时目录清理。无正常数据库、仓库、服务、权限配置、真实模型或计数调用。

## 限制与来源

共享模式不证明消除既存可写映射、管理员干预或整个DLL运行包可写性；必须另有受保护运行包／ACL及实际准入。当前不是Guard认证、生产Root、LPAC、网络或整任务停止验收。

一手依据：[CreateFileW共享模式及原句柄生命周期](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)、[ReadFile同步读取](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-readfile)、[Microsoft PE格式](https://learn.microsoft.com/en-us/windows/win32/debug/pe-format)。
