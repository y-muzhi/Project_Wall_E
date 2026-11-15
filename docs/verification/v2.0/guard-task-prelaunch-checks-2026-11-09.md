# V2.0 原启动准备的网络、控制凭据和工作树复验

2026-11-09（Asia/Hong_Kong），Windows x64／NTFS，工作树基线 `28a7c9e`。对照 BE 7.3.1—7.3.4、7.4.2／7.4.4。 [独立迭代](../../iterations/pending/v2.0/WALL-E.执行器配置隔离与生效迭代_V_2.0.md)

- WFP 夹具用 Win32 ABI 读回、枚举及事务接口覆盖六层跨子层筛查，验证外部软允许、其他包及停用对象通过，外部硬允许、callout、未知动作拒绝。认证管道另核对原规则已安装后的 `VERIFY_NETWORK_POLICY` 分项，以及原 RELEASE 中读回失败的保留顺序。当前系统的真实 WFP 写删、策略仲裁及连接未验证。 [Microsoft WFP 仲裁](https://learn.microsoft.com/en-us/windows/win32/fwp/filter-arbitration)
- 同账户认证管道验证原控制凭据可创建、只读查回、重复创建拒绝、只有引用和承诺写入原私有记录、显式环境注入及原 STOP 撤回。实际本地 TCP 表按四元组核对连接对端 PID；向错进程连接时夹具收到零个 HTTP 请求，正确时收到固定健康请求和匹配的 Basic 头。尚未执行固定 OpenCode。 [Microsoft TCP 行](https://learn.microsoft.com/en-us/windows/win32/api/tcpmib/ns-tcpmib-mib_tcprow_owner_pid)
- 同账户原目录／FileID 验证，Guard 独立枚举并锁读目标文件。实际管道拒绝同长度原位改写，原字节恢复后复验通过。NTFS 真实文件命名数据流拒绝。 [Microsoft 文件流信息](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_stream_info)
- 使用 `tools.quality_gate.environment`、`WALLE_TEST_CONTROLLER_POSITIVE=1`、自动清理 `--basetemp`，运行 `.venv/Scripts/python.exe -B tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider --tb=short`。快速回归为 `test_v20_windows_task_endpoints.py`、`test_v20_wfp_install_transaction.py` 及 `test_task_runtime_workspace.py`，**30 项通过**（3.45 秒）。首轮管道发现凭据回执文件名未加入私有记录白名单，加入后通过。另一轮 HTTP 测试夹具用 32 位十六进制控制方引用，改为原合同要求的 64 位后通过。扩大组合包括完整 `test_authenticated_task_workspace_publication` 及以上三组，再加 `test_v20_guard_task_network.py`、`test_v20_windows_config_source.py`、`test_v20_opencode_runtime_bundle.py`、`test_v20_windows_lpac_profile.py`、`test_v20_windows_job.py`、`test_v20_windows_private_record.py`。最终 **130 项通过**（208.63 秒），仅既有 Starlette 弃用提示。
- 应用 304 文件 Ruff 格式、13 个应用模块 Ruff lint、18 个本轮源码／测试文件的行尾空白及 Git 空白检查通过。实际测试 profile、监听、进程及测试目录均已清理。两份正式设计摘要维持基线，5173／5174／8000 无 TCP 监听。
- 完整 PREPARE／RELEASE 仍为 UNKNOWN，业务 CREATE／RESUME 仍封闭。最后派发边界、实际流量、固定 OpenCode 与正式 SYSTEM／普通后端双账户待验证。仓库登记的数据库依赖回归受既有 `db20-r29` 来源摘要差异影响，未执行。
