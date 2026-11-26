# OpenCode 控制端口启动诊断验证（2026-11-26）

V2.11 事项 22 修订 11。使用 V2.0 后端 §7.3.2、§7.4 与[上次 Windows 实机记录](coding-windows-task-route-2026-11-26.md)接续。本次未改正式服务、代理、Windows 审计策略、WFP、任务能力或用户仓库，模型与计数请求为 0。

- 原启动鉴权挑战接入现有 TCP 监听所有权检查。端口无监听时继续按原期限等候，监听属于其他进程或占用地址不符时封闭启动。已连接后仍核对 TCP 对端 PID 和原进程身份，之后才发送 HTTP。
- TCP 拒绝、TCP 超时和 HTTP 读写超时使用不同固定故障码。原 START_INSTANCE 工作进程记录操作编号及故障码，再执行原 UNKNOWN 和停止围栏处理。正常启动等待和原有未证实传输失败仍沿原路径。
- 用 `.venv/Scripts/python.exe -B tools/quality_python.py` 运行 `test_v20_windows_task_endpoints.py::test_control_startup_transport_diagnostics`、`test_v20_opencode_instance_control.py::test_startup_only_retries_original_transient_control_results`、`test_v20_windows_wfp.py` 和 `test_v20_wfp_install_transaction.py`，共 47 项通过。诊断路径注入传输故障，使用本进程的真实 Windows 进程身份。后端 Ruff 格式和改动源码的 Ruff 静态检查通过。
- 当前 Codex 执行会话能以临时端口绑定和监听 IPv4。普通进程到自己监听端口的直接 TCP 连接在 connect 返回 10013。WFP 原生只读会话打开返回 5，Windows Security 拦截事件查询同样拒绝访问。本次普通连接结果仅适用于 Codex 执行会话。上次主机的受管入站仍待重新观测。
- 后续需要在有主机诊断权限的实机环境，使用固定隔离测试 SID 与端口复现原连接。在同一次复现中，以目标端口、SID、方向定位分类丢弃及其 filterId，并对应同次采集的 WFP 过滤器记录。临时诊断产物清理后只保留简要 Markdown。正式入站尚未打通，8001 未更新。[微软 WFP 诊断](https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/troubleshooting-uwp-firewall)
