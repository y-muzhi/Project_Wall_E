# V2.0 整组只读依据的固定计划与关闭证据

2026-11-08（Asia/Hong_Kong），Windows x64／NTFS，工作树基线 `28a7c9e`，项目 .venv Python 3.13.5、固定 SQLite 3.54.1。对照 BE 7.3.1—7.3.4、7.4.4 及 START_INSTANCE。 [独立迭代](../../iterations/pending/v2.0/WALL-E.启动固定依据准备_V_2.0.md)

- 同账户真实 Guard 测试进程和普通后端子进程分别从原任务清单核对完整计划。Guard 按编号交接实际 NTFS 最小写句柄，后端从原封存复制非 ASCII UTF-8／CRLF 文件及空文件，关闭写入后读回摘要。Guard 保持原读句柄，核对每个原回执、目录 FileID、精确目录清单及原 PREPARE 状态，追加一次私有关闭证据；后端独立核对组摘要。两进程通过夹具的临时文件交换传输元数据，Guard 不读取依据正文。
- 负向覆盖缺回执、额外文件、错误编号／作用域／计划摘要／FileID、取消、同长度篡改、仍有写句柄时保留原 owner、STOP 先于关闭发布。故障注入模拟写入后回复丢失，核实可查回原证据；模拟结果未知且无可观察记录，再次调用保持未知，无第二次发布。实际认证来源预检管道接受计划摘要并拒绝畸形值；该阶段不新建 PREPARE 接收记录。
- 通过 `tools.quality_gate.environment`、隔离 `--basetemp`、`WALLE_TEST_CONTROLLER_POSITIVE=1` 运行 `.venv/Scripts/python.exe -B tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider --tb=short`。首轮原生整组 5 项通过（10.62 秒）。补齐未知回复与计划摘要的管道检查后，最终 **42 项通过**（140.59 秒）。范围为 `test_v20_windows_task_basis.py`、`test_task_start_basis.py`、`test_task_start_conditions.py`、`test_v20_windows_task_directories.py`、`test_v20_windows_private_record.py` 及 `test_v20_guard_control_git_transport.py::test_task_source_handoff_verifies_exact_original_ntfs_objects`。仅有既有 Starlette 弃用提示，命令退出 0，自动清理的测试目录已核对不存在。
- `.venv/Scripts/python.exe -B -m ruff format --no-cache --check backend/app` 核对 284 文件，六个改动应用模块 Ruff lint 和 `git diff --check` 通过。Git 提示既有前端文件 CRLF。
- 关闭证据覆盖原 PREPARE 未确认时的组状态和原句柄。生产整组传输、ACK／CREATE 前后的原句柄复验、进程重启后仅观察的归属路径、SYSTEM 与普通后端双账户、实际 LPAC／WFP、运行包、启动及完整停止释放仍待。V2 运行准入保持阻断。
