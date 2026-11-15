# 原控制方令牌挂起创建及恢复（2026-11-05）

- 代码状态：基于28a7c9e的V2未提交实现；新增infrastructure/windows_native_process.py及专项。BE7.3／7.7现行规则，未改正式设计／用户服务／正常数据。
- 输入／输出／不变量：输入为原ControllerPrimaryToken、固定ExecutablePin、独占Job、原scope GuardStandardIO、实际LocalPathGuard及原LaunchFence；当前只登记固定MinGit的('--version',)，其余参数／程序拒绝，TASK／CHECK_DRIVER拒绝。原输入SHA绑定scope、控制方／token、文件及目录身份、参数、IO及限制。CREATE／RESUME必须分别已持久MAY，回复未知只观察；调用方必须串行管理原资源生命周期、在返回前保存资源归属。
- 真实路径：唯一CreateProcessAsUserW，不启用权限、不改会话，不提供CreateProcessW／凭据／服务令牌替代。显式程序与参数、固定版本核验环境、隐藏／Unicode／挂起／STARTUPINFOEX；同次创建附HANDLE_LIST及JOB_LIST，仅原3 child pipe继承。
- 创建后在恢复前核对原进程／线程句柄非继承、真实image／user／非AC／非提升、primary token原authentication LUID及session、实际Job及限制；借原程序锁定，始终保留原process/thread。
- 生产LaunchJournal实际prepare→持久CREATE MAY→Native创建→保存原resource_ref→持久RESUME MAY→ResumeThread ACK=1→保存ACK已在专项打通。0／2／FFFFFFFF或回复丢失不再次Resume。创建成功后验证失败，异常保留原owner；API FALSE的输出字段不作句柄所有权；1314直接不可用、不降级。
- observe仅核对原句柄PID／创建时间及Wait／退出码。首次错误地退出后重查image，实际QueryFullProcessImageName不可用，导致2失败／7夹具错误；已修，不重新打开PID。未完整取得身份的原创建仍须等待原句柄signaled后才可关闭；此清理不当Task STOP。
- close不关闭仍活动／未知原进程；只关闭本对象原process／thread／查询token，部分失败保留原引用；Job／控制方token／program pin／IO／directory仍归原所有者管理。进程退出、Job空或单个资源释放均不宣告整任务停止。

## 本轮检查

获准普通非提升环境，固定SQLite启动器＋quality_python，独占隔离临时根：
test_v20_windows_native_process.py／test_v20_windows_executable_pin.py／test_v20_windows_stdio.py／test_v20_windows_controller_token.py，**87通过，26.93秒，无正向跳过**。覆盖真实CreateProcessAsUser固定Git挂起、原普通用户／logon、Job、持久恢复后退出0、未登记程序／参数拒绝、STOP先闭原nonce、创建输出不可信、创建后故障保留、恢复未知一次派发、部分关闭重试；原令牌／IO／文件锁受影响回归一并通过。

默认环境运行168文件Ruff格式、两个新增生产模块Ruff check及git diff --check通过。最初新增模块import／with及异常捕获的lint问题已按配置修复，没有关闭规则。保留既有Starlette的httpx弃用提示。测试输出仅内存，专属临时文件清理，无运行中测试进程／服务。

## 未覆盖与下一步

本单元只有固定版本命令Native adapter，不是全部Git协议、生产Guard注册／Pipe程序认证、控制方退出watchdog、Guard崩溃或LPAC／ACL／WFP准入。未读取实际版本stdout作为本单元判据；程序原包版本的真实stdout证据见固定Git对象向量专项。版本探测使用固定NUL空配置流及最小环境，不替代7.7完整配置预检。runtime_admitted仍false。

完整运行包保护、全部命令逐项登记、Guard原资源持久登记／认证通道仍需接入。无系统安装、权限或网络策略更改、正常仓库／数据库写入、真实模型／计数调用。

一手依据：[CreateProcessAsUserW及令牌访问权／1314](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessasuserw)、[ResumeThread返回原suspend count](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-resumethread)、[标准IO原句柄归属](https://learn.microsoft.com/en-us/windows/win32/procthread/creating-a-child-process-with-redirected-input-and-output)。
