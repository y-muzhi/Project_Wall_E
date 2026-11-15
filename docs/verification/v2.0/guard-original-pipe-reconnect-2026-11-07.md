# Guard 原端点重连与正常启动发布校验

- 2026-11-07，V2 工作区。Guard 保留原首次创建的本机命名管道句柄。旧 IO 仍借用时拒绝断连，借用退役后仍须由原管道零字节检查确认旧对端已断开。可靠 DisconnectNamedPipe 后复核原安全描述符和端点属性，新连接另建 IO／帧所有者，重走原进程和包准入。
- 实际登记丢 CREATE 回执用例改为复用同一原 server 句柄。原后端关闭旧连接，Guard 断连后重新接受，再对同一原作用域执行 STOP／OBSERVE／RELEASE。原资源可证明已清理，业务记录仍 UNKNOWN。程序包准入仍是隔离测试端口。
- 初轮原生组合 65 通过、2 项登记连接超时。增加仅在测试临时目录使用的子进程诊断，定位正常 load_release 拒绝旧源码摘要。对 db20-r15.sources 逐项验算，唯一变化为新增两条读路由的 backend/app/service.py。
- 执行 `tools/python-v20.py tools/schema-v20-release.py --release-id db20-r16` 成功，manifest SHA256 `0973bb5f4694aa87573cc9a5b1bb89ef82cb748d43f69fea07f55bf102b7441f`。objects.v1.json、fresh.v1.sql、upgrade-151.v1.sql 和 r15 字节一致，既有发布目录均保留。仅准备仓库资源，没有升级用户库或启动用户服务。
- r16 最终 `test_v20_windows_guard_pipe.py`、`test_v20_windows_guard_pipe_io.py`、`test_v20_guard_pipe_frames.py`、`test_v20_guard_control_git_transport.py`、`test_v20_startup.py`、`test_v20_published_schema.py`，71 通过，55.74 秒。覆盖原端点重连、失效流、实际固定 Git、正常启动 pin；Windows 测试进程和临时产物清理。
- Native 接口依据。[DisconnectNamedPipe](https://learn.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-disconnectnamedpipe)、[ConnectNamedPipe](https://learn.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-connectnamedpipe)、[PeekNamedPipe](https://learn.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-peeknamedpipe)
