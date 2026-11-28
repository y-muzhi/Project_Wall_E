# V2.2 Linux 执行通道与 HTTP 检查

2026-11-28（香港时间）。基线为 `6c2c8ed`。本地 `codex/v22-development-checks` 检出增量未发布。依据 V2.01 后端 4.20、6.7、7.11.7、7.11.9。隔离验证未导入开发库或真实模型凭据。

- 在 Mac ARM64 固定运行时的临时源码副本执行 `pytest`，覆盖 `test_linux_execution_channel.py`、`test_linux_native_endpoint.py`、`test_linux_native_request.py`、`test_linux_owned_check_http.py`、`test_v20_check_case_evidence.py`、`test_v20_owned_check_http.py`。32 项通过，三个只适用于 Windows 的联网归属用例在 Linux 跳过，原 Starlette 弃用警告一条。
- Linux pathname `AF_UNIX/SOCK_SEQPACKET` 原对端使用 `SO_PEERPIDFD` 固定，逐报文核对 `SCM_CREDENTIALS`。测试覆盖 accept 前到达的报文、隔离报文边界、跨进程继承后误用、重复字段／非法编码、超长、附带 FD 清理和原资格撤销。当前版本拒绝所有 FD，ATTACH 的单 pidfd 特例和安装身份、持锁、原范围联合准入待接。
- `NETLINK_SOCK_DIAG` 核对实际 TCP 反向四元组、监听及已接受连接的 uid／inode／cookie，原 pidfd 验证存活。实测未 accept 时不发送字节，拒绝通配监听，以及核对原 socket。独立来宾在非特权、仅回环网卡下，通过固定 OpenCode 1.19.5 的真实监听及已接受连接检查，之后才发送 Basic 并收到健康响应。实验使用合成凭据与固定程序，未跨角色证明正式 AppArmor 策略及原任务窗口。
- 原生请求的 BEGIN／DATA／COMMIT 通过真实 Unix 报文完成绑定、规范输入摘要和方法白名单检查。拒绝跨实例、跳号、未知字段或方法、超期限以及输入摘要不符。原生控制器的持久保留请求、逐方法授权、响应帧以及 STATUS／CANCEL 仍待接。
- Testing HTTP 复用原 CasePack 的请求构造、断言求值和结果记录。对实际本地 HTTP 服务的测试验证两个原步骤、302 不跟随、错误来源拒绝、回执截断标未知、重开读取成功回执和已有意图无结论时拒绝重发。该回执是单检查执行证据，应用 TestingTask、最终验收报告及可信收尾仍未执行。
- `ruff format --no-cache --check backend/app` 使用锁定 0.17.3，通过。Windows AppContainer 下原有 HTTP 回归为 1 通过、2 失败。相同环境载入 HEAD 原实现复测结果一致，根因为 Windows TCP 归属表不可用。该环境的系统 Python 缺少 FastAPI，跨平台证据专项以 Mac 固定运行时结果为准。

切入点为 `TestingCliWorker` 的平台执行接入、`settle_case` 的 Linux 原进程及停止／清理证据投影、OpenCode 固定方法和原任务控制。开发与集成部署仍使用原发布。未运行真实供应方、模型计数、正式应用报告或现场切换。
