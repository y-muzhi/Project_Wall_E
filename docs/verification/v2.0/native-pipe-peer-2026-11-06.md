# 原命名管道连接方身份检查（2026-11-06）

V2未提交工作区；BE0.17-draft-17的7.3.1—.3及7.7.6，设计及Schema db20-r14不变。新增windows_pipe_peer.py／test_v20_windows_pipe_peer.py；无HTTP、Guard安装、ACL／网络／正常数据或用户服务更改。

## 实现与边界

NamedPipePeerLease对原端点复制不可继承句柄，核对真实端点角色及本机owner进程、OS返回的peer PID和已登记完整NativeProcessIdentity，再保留一份原ObservedProcess。实际用户、程序、创建时间、token事实及原ExecutablePin的路径／FileID／内容均核对；CLIENT拒绝提升／服务令牌，两种控制peer都拒绝AppContainer／未知LPAC。每次核对沿原进程句柄，不重开旧PID。程序lease及借用中的peer不能被关闭，失败保留原owner供清理。

只提供原生连接事实组件；expected／program／用户来自可信登记，不能来自RPC自报。当前未创建生产端点／受控DACL、未完成保护运行包或owner_epoch协议，也没有调用生产ControlGitRegistry。不因程序文件hash或一次进程身份正确宣称完整认证、源码包准入或LPAC隔离。fixture管道为随机名字、新建本机端点，普通进程测试；真实Guard持久部署仍待实施。

## 实际检查

环境：普通非提升Windows／NTFS、.venv Python3.13.5、现有锁定Win32组件；quality_gate.environment＋quality_python.py，-q -p no:cacheprovider --tb=short及自动清理临时--basetemp。每份fixture以原OwnedJob创建隐藏短期Python peer，保留实际工作进程和Job成员句柄，最终只终止本Job并等原句柄／空成员再关闭与清理；不装服务、不改既有ACL，不调用模型／外网。

- 新专项：test_v20_windows_pipe_peer.py，18通过、1条既有Starlette弃用警告，1.80秒。真实双端角色、原普通控制方token组合、原进程／程序借用寿命、错误创建时间、另一有效Git程序、角色／用户错配、原peer退出和server断连均覆盖；无PID重开。
- 相关回归：该文件＋test_v20_windows_controller_token.py／test_v20_windows_process.py／test_v20_windows_executable_pin.py，78通过、1同类警告，2.88秒。215文件Ruff format、模块lint及git diff --check通过。
- 当前没有活动检查或待取得回执；所有临时端点／目录及本Job资源随fixture清理。没有保留原日志、JSON或截图，程序／Schema／目录pin未因本组件改变。

## 官方API依据

实施前核对微软[客户端进程ID](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getnamedpipeclientprocessid)、[服务端进程ID](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getnamedpipeserverprocessid)、[管道端点类型](https://learn.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-getnamedpipeinfo)、[句柄复制](https://learn.microsoft.com/en-us/windows/win32/api/handleapi/nf-handleapi-duplicatehandle)及[本机／首次实例标志](https://learn.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-createnamedpipew)。本文不宣称服务端标志或DACL已由本组件实现；这些是下一端点单元的必要输入。
