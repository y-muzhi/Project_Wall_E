# V2.0 已封存 TASK 的 Guard 管道控制

2026-11-08（Asia/Hong_Kong），Windows x64／NTFS，工作树基线 `28a7c9e`，固定 SQLite 3.54.1。对照 BE 0.17-draft-17 §7.3.1—7.3.4、§7.4.4 和原 Guard 动作约定。 [独立迭代](../../iterations/pending/v2.0/WALL-E.Guard原技术动作与资源准备实施细化_V_2.0.md)

- 三个真实命名管道场景覆盖已部署、缺部署和原 CREATE 结果未知。独立普通 Windows 后端子进程持有真实 ProcessLock，Guard 验证 pipe peer 与程序映像。受保护程序正向准入和 WFP 状态使用夹具，原技术记录与封存使用真实临时 NTFS。夹具先完成当前控制方登记，再写模拟 CREATE 意图。
- 核对了新 TASK PREPARE 不写记录、已有 TASK 请求伪装成 CONTROL_GIT 不转发、原绑定错误拒绝、STOP 原 ACK 重放、迟到 CREATE 拒绝、未派发规则只删除一次，以及原 RELEASE 继续未知但 OBSERVE 查到原规则缺失。可能已有 CREATE 时 STOP 只封闭原 nonce 并保留未知，原规则保留。
- 扩展回归 122 项通过、1 项失败（97.95 秒）。失败用例在首次程序登记前写入模拟 CREATE 历史，命中现有 `CONTROLLER_RECORD_CANNOT_ATTEST_PRIOR_LAUNCH`。修正夹具先经实际管道登记后，TASK、WFP、原动作记录及恢复专项 116 项通过（13.37 秒）；处理器追加原 peer 与请求复验后最终同组 **116 项通过**（13.62 秒）。扩展回归中既有 Control Git、宿主和回执共 7 项通过。仅既有 Starlette 弃用提示。
- 命令通过 `tools.quality_gate.environment` 和临时 `--basetemp` 执行 `.venv/Scripts/python.exe -B tools/python-v20.py tools/quality_python.py -q -p no:cacheprovider --tb=short`，选取 infrastructure 的 `test_v20_guard_task_network.py`、`test_v20_wfp_install_transaction.py`、`test_v20_windows_wfp.py`、`test_v20_guard_action_journal.py`、`test_v20_runtime_launch_journal.py`、`test_v20_guard_recovery.py`，以及 `test_v20_guard_control_git_transport.py` 的 TASK 管道、原固定命令、宿主原端点和原回执绑定场景。临时目录已清理。
- 应用 278 文件 Ruff 格式、5 个改动源码 Ruff lint 及 `git diff --check` 通过。既有前端文件有 CRLF 提示。
- 本轮证据限已有原封存的当前控制方。新 TASK PREPARE 需要受信目录／LPAC／Job／入口及受保护部署。跨控制方 TASK 恢复、已派发实例原 Job 的退出、完整 RELEASE、实际 WFP 规则写删与连接仍待。
