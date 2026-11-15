# V2.0原生进程身份与只读生命周期

日期：2026-11-05；HEAD 28a7c9e。BE7.3／7.7要求的Guard基础原语，尚未接实际Guard／生产认证。仅当前检查进程及本轮自有短进程，未探测／停止用户服务，没有ACL／防火墙／系统安装更改。

实现windows_process.py：
- 只请求QUERY_LIMITED_INFORMATION与SYNCHRONIZE，非继承真实进程句柄；Token仅QUERY，不启动／终止／提权／模拟。
- GetProcessId＋GetProcessTimes的完整64位creation time（私有16位hex，避免浮点丢失）＋内核实际image路径／user SID／AppContainer SID／elevation。可带原NativeProcessIdentity重开，PID相同但创建时间／程序／令牌不符即拒绝。持有句柄后不凭旧PID重开；已关闭观察拒绝。
- 以WaitForSingleObject(handle,0)区分真实进程信号；只有signaled才读退出码。退出259仍识别为EXITED，不把STILL_ACTIVE数值无限当运行中。根退出不表示整个进程组停止或任务完成。
- 固定DWORD令牌信息按实际大小直接读取。TokenIsLessPrivilegedAppContainer枚举不能当查询能力证据：现场Win10.0.26200，GetTokenInformation(46)返回87／size0；只读诊断NtQueryInformationToken同类返回C0000003。此特定“查询不支持”保存is_lpac=null；非AppContainer可确定false，其他查询失败仍报未知错误；null不得作为LPAC执行资格。没有普通AppContainer降级。后续真正LPAC边界需创建属性、实际ACL／网络及能力专项证明。

专项：新test_v20_windows_process.py，最终12通过（1.02秒）；真实当前句柄、SID／flags、不可继承、错创建时间／image／SID拒绝、自有进程运行→signaled退出259、关闭后不重开、未知LPAC不冒充权限。首轮8通过／3失败定位到LPAC查询不支持；同时实际发现TokenElevation的空缓冲长度查询返回ERROR_BAD_LENGTH24，按固定DWORD处理修复，非放宽令牌错误。

命令：tools/python-v20.py tools/quality_python.py backend/tests/infrastructure/test_v20_windows_process.py -q -p no:cacheprovider --tb=short --basetemp <项目.tmp专属目录>，配tools.quality_gate.environment，普通权限；161文件Ruff格式及git diff --check通过。自有进程／目录均finally清理，无日志／JSON报告留存。

一手依据：[GetProcessTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes)、[QueryFullProcessImageNameW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-queryfullprocessimagenamew)、[WaitForSingleObject](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject)、[GetExitCodeProcess](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getexitcodeprocess)、[TOKEN_INFORMATION_CLASS](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ne-winnt-token_information_class)及Microsoft win32metadata实际winnt.h。只读现场诊断未进入持久原始日志或业务库。

剩余：程序文件原生身份／包摘要、认证管道、持久nonce关闭、挂起创建并原子归Job、LPAC／WFP／ACL、控制方／Guard退出回收、整个Job停止／清理证明均未完成。这里报告的是OS事实，不是完整进程授权／隔离／STOP验证，不能据根EXITED释放任务名额。
