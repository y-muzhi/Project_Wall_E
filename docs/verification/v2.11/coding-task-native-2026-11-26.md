# 本机受管代码任务启动核对

2026-11-26，香港时间。V2.11 事项 22，依据 V2.0 后端设计 §7.3.1–§7.3.3。工作区原有改动保留，产品源码及运行资源未修改。

## 实机结果

使用已核验的 OpenCode 1.19.5 Windows 可执行文件，启动前后核对 SHA-256。临时工作区复用 `v20_primary_lpac_probe.primary_probe` 的普通用户主令牌、LPAC、Job、原镜像和令牌校验。用临时夹具分别运行 `--version` 及 `serve --hostname 127.0.0.1 --port <临时端口>`，最多等待 15 秒。任务没有附加本机网络策略，全部子进程和临时目录随夹具回收。

| 任务身份和资源 | 实测版本查询 | 实测回环服务 |
| --- | --- | --- |
| LPAC、空 capability、128 MiB Job | 退出 `0xC0000409`，stderr 报 2,376,144 字节分配失败 | 退出 `0xC0000409`，无回环响应 |
| LPAC、空 capability、2 GiB Job | 退出 `0x80000003`，`WSAStartup` 返回 10107 | 同一初始化错误，无回环响应 |
| LPAC、仅 `registryRead`、2 GiB Job | 退出 0，报告 1.19.5 | 退出 1，报告 `ServeError`，无回环响应 |
| LPAC、`registryRead` 加 `lpacCom`、2 GiB Job | 退出 0，报告 1.19.5 | 退出 1，报告 `ServeError`，无回环响应 |

- 单独的固定 Python 原生探针在仅有 `registryRead` 的 LPAC 中创建 IPv4、IPv6 TCP socket，均返回 10013。普通身份在同一机器可绑定、监听临时 IPv4 回环端口。空 capability 的 Python 对照更早退出，Windows 状态 `0xC0000022`，该次探针未取得 socket 结果。对照支持分别处理运行时初始化与网络监听。
- Microsoft 文档说明 LPAC 访问注册表需要 `registryRead`。Winsock 10107 是通用系统调用错误，也可由协议目录相关的注册表调用失败产生。本机对照确认了加权限后版本查询恢复，未追踪到具体注册表项。[LPAC 能力](https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer) [Winsock 错误码](https://learn.microsoft.com/en-us/windows/win32/winsock/windows-sockets-error-codes-2)
- BFE 和 Windows Defender 防火墙服务均运行。用普通身份读取 WFP 事务返回 Windows 5。现有只读测试允许此结果，这一现象未核验管理员可见的过滤层及实际策略。
- 工作区虚拟环境运行 `python -B -X utf8 -m pytest -q -p no:cacheprovider --tb=short`，限定 `test_v20_windows_wfp.py`、`test_v20_wfp_install_transaction.py`、`test_v20_windows_task_endpoints.py`，38 项通过。专项验证现有计划、事务和端点逻辑。真实受管 TASK 的 WFP 正反向网络证据仍缺。

## 接续

- 查核 `windows_task_native_launch.py::_lpac_capability_names`，正式 TASK 当前返回空 capability。现有 `tools/windows_guard_bootstrap.py` 只组装仓库登记 Guard，未绑定 TASK 运行包、网络部署和本机准入文件。`guard_task_deployment.py::TaskRuntimeAdmission.verify` 校验 SYSTEM 侧固定记录，代码中未发现对应 TASK 记录的正式生成入口。
- 接续实施应固定 OpenCode 实际所需的最小系统读取能力和已验证的 Job 参数，在独立 Windows 环境经 Guard 安装和观测任务 SID 的严格 WFP 规则，验证本任务控制端口和模型回环、IPv4 与 IPv6、其他端口／任务、直连及 DNS 拒绝，随后依据真实结果生成准入记录。单因素对照的 2 GiB 为本轮测试额度，正式执行配置需另行验证。实际 Coding 供应方和价格准入仍待单独完成。
- `http://127.0.0.1:8001/` 实际 HTTP 200，监听 PID 45120。本机没有可调用的 WindowsSandbox.exe 或 Hyper-V Get-VM 入口。本轮未更改 Windows 系统级策略及现有服务，未调用真实模型或计数接口。仓库登记和本机 OpenCode 写文件至 Git 的先前证据见[本机代码产出](coding-output-local-2026-11-26.md)。
