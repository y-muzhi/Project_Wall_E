# 原控制方有效文件权限核验（2026-11-05）

代码状态为28a7c9e后的V2未提交实现。新增infrastructure/windows_access_check.py及test_v20_windows_access_check.py，承接BE7.3.1—.2受保护运行包／资源权限规则；未改正式设计。

输入必须是原ControllerPrimaryToken与已打开LocalPathGuard。由原普通token复制仅QUERY的Identification impersonation token，核对实际user／authentication LUID／session、非提升／非AC及非继承；不模拟Guard线程、不更改权限或会话。GetSecurityInfo读取实际同对象owner／group／DACL，AccessCheck(MAXIMUM_ALLOWED)取得该原用户有效权限并保存描述符摘要；不是只读属性或静态ACE文本猜测。

FILE检查写数据／追加／EA／属性／DELETE／WRITE_DAC／WRITE_OWNER；PACKAGE_DIRECTORY还检查DELETE_CHILD；ANCESTOR检查删除／删除子项及EA／属性／ACL／所有者变更，禁止替换祖先，不把创建无关兄弟目录当替换。角色须与真实对象类型一致。未知API结果／形状／对象变化拒绝；关闭／LocalFree失败保留原token／句柄／内存描述符供原owner清理，关闭中不继续查询。

## 实际检查

获准普通非提升环境，固定SQLite启动器＋quality_python，test_v20_windows_access_check.py **25通过，1.45秒，无正向跳过**：
- 原持有普通控制方token及原文件身份、真实用户可写文件拒绝。
- 仅设本轮临时文件只读属性仍具有owner WRITE_DAC，明确拒绝；finally恢复本轮文件属性以清理。
- 只读观察现有C:\Program Files目录及Chrome程序，真实有效权限无上述写权，通过相应只读事实判定。未启动Chrome、未把它登记为产品资源或后端程序。
- 原生API失败／无效grant形状、角色不符、token关闭失败及安全描述符释放失败保留覆盖。

171个生产文件Ruff格式、新模块Ruff check及git diff --check通过。既有Starlette httpx弃用提示保留；自有临时对象已清理，不留原始JSON／日志或活动进程。没有修改系统目录／ACL／所有者／权限，也没有正常业务／服务或真实模型／计数调用。

## 边界

这是只读权限原语，不是完整包闭包／所有祖先准入、来源签名、认证Pipe或LPAC／WFP证据。包准入必须把这些事实接入原已登记程序／完整资源核验，并在实际创建／访问边界重查；普通Python进程image不能成为已认证后端的替代。当前runtime_admitted=false。

一手依据：[AccessCheck实际token及MAXIMUM_ALLOWED](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-accesscheck)、[GetSecurityInfo按句柄读取描述符](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-getsecurityinfo)、[文件权限及删除子项边界](https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights)。
