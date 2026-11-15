# V2.0 普通控制方primary token及实际Job成员

日期：2026-11-05，HEAD 28a7c9e。范围仅本轮自有Job／Python夹具，未以复制令牌启动程序、安装服务、启用权限或修改当前用户／系统配置。

windows_controller_token.py只接受原Held ObservedProcess及已认证原NativeProcessIdentity，重新核对真实内核程序／创建时刻／SID与存活，不按PID重开。拒绝Guard当前进程、AppContainer／LPAC、提升令牌、SYSTEM／服务SID及线程模拟。DuplicateTokenEx生成不可继承primary copy，只请求QUERY／DUPLICATE／ASSIGN_PRIMARY（0xB），核对user、authentication LUID、session及真实token统计；创建借用前后再核对。无服务身份、当前账户、口令登录或关闭限制的替代路径。失败清理保留未关闭原句柄及retained_owner，不丢失后再找新token。

windows_job.py新增contains_process，先原进程句柄再Job的固定锁序，通过IsProcessInJob核对真实归属，不收序列化PID。实际非成员false／非法裸PID拒绝已覆盖。模块不决定完整Task STOP。

默认AppContainer专项：token9通过／5正向跳过；获准普通非提升非AppContainer环境设置WALLE_TEST_CONTROLLER_POSITIVE=1，token／Job／process三文件最终36通过（1.52秒），无跳过。真实复制／authentication和session一致／不继承、原控制方退出拒绝、不自动修复继承位、Guard线程模拟拒绝并由夹具RevertToSelf、关闭失败保留原句柄后恢复清理均已覆盖。随后新增Job非成员／裸PID边界，默认环境两文件19通过／5正向跳过（1.86秒）。165文件Ruff格式及diff通过。

首次正向组合36条断言通过但4项fixture清理WinError32，整体失败；修复为由实际Python工作进程原子发布ready PID，核对其原Job归属，并保留原成员句柄。终止后等待每个原process signaled及原launcher退出，再核实Job无成员，最后关闭句柄和清理目录。未添加猜测延时或以重试删除掩盖状态。首次外层临时目录在子进程结束后清理成功，后续专项也无残留；不把active=0当进程资源清理完成。夹具ready不是生产Guard认证。

命令：tools/python-v20.py tools/quality_python.py对应test_v20_windows_controller_token.py／test_v20_windows_job.py／test_v20_windows_process.py，配tools.quality_gate.environment及项目.tmp专属目录；正向模式仅获准环境。无原始测试报告／日志保留。

边界：此组件不是Pipe／程序签名认证，调用方须先完成认证；生产CreateProcessAsUser／STDIO白名单／LPAC创建、Guard服务及受保护运行包、WFP／完整停止仍未接。未复制供应商凭据或读取设计正文，当前没有可准入执行配置。

一手依据：[DuplicateTokenEx](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-duplicatetokenex)、[CreateProcessAsUserW](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessasuserw)、[TOKEN_STATISTICS](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-token_statistics)、[IsProcessInJob](https://learn.microsoft.com/en-us/windows/win32/api/jobapi/nf-jobapi-isprocessinjob)、[ExitProcess](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-exitprocess)。
