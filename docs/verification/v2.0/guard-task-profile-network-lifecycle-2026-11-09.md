# V2.0 原认证 profile、停止回收与 WFP 分项证据

2026-11-09（Asia/Hong_Kong），Windows x64／NTFS，工作树基线 `28a7c9e`，固定 SQLite 3.54.1。对照 BE 7.3.1—7.3.4、7.4.2、7.4.4。 [独立迭代](../../iterations/pending/v2.0/WALL-E.执行器配置隔离与生效迭代_V_2.0.md)

- 同账户真实 Guard 认证管道，原 `PREPARE_PROFILE`／`VERIFY_PROFILE` 绑定同一文件和 Job 证据。缺原 profile、重复分配、未安装规则、提前 RELEASE、关闭后重开和错误绑定均被拒绝。实际原 Job 插入一个自有挂起探针时 STOP 保持 UNKNOWN；探针退出后 STOP 只确认原未派发范围封闭。原 RELEASE 删除实际临时 profile，原路径不存在，Job 随后关闭。原 PREPARE／RELEASE 均未确认完整。
- 使用 `tools.quality_gate.environment`、`WALLE_TEST_CONTROLLER_POSITIVE=1`、自动清理 `--basetemp` 运行 `.venv/Scripts/python.exe -B tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider --tb=short`，目标为 `backend/tests/infrastructure/test_v20_guard_control_git_transport.py::test_authenticated_task_workspace_publication[execution_profile]`。首个真实管道专项 **1 项通过**（27.31 秒），仅既有 Starlette 弃用提示。
- WFP 组合专项覆盖缺安装意图不能核对；原意图与同范围规则读回齐备时返回分项证据。模拟规则删除后首次缺失读回失败，实际 profile 和原 Job 保留；重复原 RELEASE 只读回规则缺失，不重复派发删除，随后释放实际 profile。WFP 安装、删除及读回使用受控夹具。
- 同一隔离命令扩展到整个 `test_authenticated_task_workspace_publication`，以及 `test_v20_guard_task_network.py`、`test_v20_wfp_install_transaction.py`、`test_v20_guard_controller_owner.py`、`test_v20_windows_lpac_profile.py`、原 Job／进程／目录／私有记录／有效访问与运行包／系统配置专项，最终 **180 项通过**（196.08 秒），仅既有 Starlette 弃用提示。扩展命令首轮误用 WFP 测试文件名，pytest 未运行；改为实际的 `test_v20_wfp_install_transaction.py` 后通过。
- 应用 302 个文件 Ruff 格式、8 个改动应用模块 Ruff lint、11 个本轮源码／测试文件行尾空白及 Git 空白检查通过。隔离任务进程、临时 profile 和自动测试目录均已清理。复核 5173／5174／8000 无 TCP 监听，两份正式设计摘要维持接续基线。
- 正式 SYSTEM／普通后端双账户、真实 WFP 写删与跨子层仲裁、连接和原入口凭据未覆盖，业务 CREATE／RESUME 仍封闭。仓库登记的数据库依赖回归受既有 `db20-r29` 来源摘要差异影响，未执行。
