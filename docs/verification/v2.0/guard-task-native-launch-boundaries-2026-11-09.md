# V2.0 原部署、挂起创建、恢复及平台停止

2026-11-09（Asia/Hong_Kong），Windows 11 AMD64／NTFS，工作树基线 `28a7c9e`。对照 BE 7.3.1—7.3.4、7.4.2、7.4.4。 [独立迭代](../../iterations/pending/v2.0/WALL-E.执行器配置隔离与生效迭代_V_2.0.md)

- 断点 1—3。原只读 WFP 事务覆盖六个授权层和四个连接／绑定重定向层。测试拒绝匹配原包的活动 callout、拒绝不可读层，确认精确其他包可排除。实际 IsWow64Process2 核对 AMD64。现场发现 Python 的系统 DLL 版本为 26100，与实际系统构建不同，改为 RtlGetVersion 读回 10.0.26200，并与系统查询交叉核对。部署索引正向采用同账户身份夹具与真实 NTFS 文件，错误端口和字节均拒绝；实际普通用户不能为运行准入。 [Microsoft ALE 重定向](https://learn.microsoft.com/en-us/windows-hardware/drivers/network/using-bind-or-connect-redirection) [Microsoft RtlGetVersion](https://learn.microsoft.com/en-us/windows/win32/devnotes/rtlgetversion)
- 断点 4—5。真实 NTFS 保留原成员读锁并阻止现有文件写入／重命名，目录末次复查发现迟到新增。原认证管道在缺部署时仍返回未知；部署与 WFP 夹具齐备时，原 profile、Job、文件、程序和凭据的合并启动输入摘要可查回。原完整 PREPARE 仍未确认。
- 断点 6—10。使用隔离 PE（固定归档校验的 Python 测试程序）、真实原普通令牌、随机临时 profile 和原 Job，实际挂起创建并核对原 token 与有效文件访问。追加原挂起回执后模拟失去确认，原 owner 查回原回执，拒绝重建。错误回执拒绝，正确回执触发一次实际 ResumeThread。覆盖 STOP 先于 CREATE 和 STOP 先于 RESUME，核对实际退出、Job 空和重复原停止回执。缺原内存 owner 时对已派发范围只报未知。测试只删除本轮随机创建且已确认退出的 profile。
- 使用 `tools.quality_gate.environment`、`WALLE_TEST_CONTROLLER_POSITIVE=1`、自动清理 `--basetemp`，以 `.venv/Scripts/python.exe -B tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider --tb=short` 执行。部署／WFP／工作树及两项管道用例 **40 项通过**（89.53 秒）；`test_v20_windows_lpac_profile.py` 最终原生组 **8 项通过**（10.54 秒）。扩大组合 **183 项通过**（247.76 秒），覆盖整个 `test_authenticated_task_workspace_publication`、WFP、TCP、工作区、运行包、LPAC、Job、私有记录及原 LaunchJournal／GuardActionJournal；只出现既有 Starlette 弃用提示。原生构建读取调整后的部署索引与正向认证管道专项复跑 **8 项通过**（63.60 秒）。
- 应用 307 个文件 Ruff 格式、13 个应用模块 Ruff lint、19 个本轮源码／测试文件的行尾空白及 Git 空白检查通过。随机 profile、回环监听、测试进程和目录均已清理；5173／5174／8000 无 TCP 监听，两份正式设计摘要维持接续基线。
- 当前正向管道使用 WFP 及正式服务身份夹具。本机普通账户只读打开 WFP 引擎返回 `WFP_LOCAL_ENGINE_UNAVAILABLE`，Win32 5。实际 WFP 写删、允许／拒绝连接、正式 SYSTEM／普通后端部署、固定 OpenCode 及生产任务的 CREATE／RESUME／已派发 STOP／完整 RELEASE 仍待。仓库登记数据库回归受既有 `db20-r29` 摘要差异影响，未执行。
