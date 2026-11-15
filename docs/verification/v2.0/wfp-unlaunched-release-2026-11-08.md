# V2.0 WFP 原规则安装和未派发释放

2026-11-08（Asia/Hong_Kong），Windows x64／NTFS，工作树基线 `28a7c9e`，固定 SQLite 3.54.1。对照 BE 0.17-draft-17 §7.3.1—7.3.4、§7.4.4，FE 0.16-draft-16 的原开始／停止状态边界。 [独立迭代](../../iterations/pending/v2.0/WALL-E.WFP原任务规则与读回核对_V_2.0.md)

- 首轮 Codex AppContainer 内 27 项通过，9 项设置失败、1 项失败。Native 夹具需要普通用户令牌创建 NTFS 私有包，隔离进程按设计拒绝 AppContainer。改用经批准的普通 Windows 用户令牌执行隔离专项，接续前原安装及枚举组合 37 项通过。
- 原网络安装回归覆盖已存 STOP、STOP 持久化失败后的当前内存封闭、控制方在原派发前开始封闭、原提交未知及读回失败。只读快照覆盖同一子层额外同 SID、其它 SID、无 SID、缺项、重复和读取失败。
- 新增释放覆盖原绑定错误、停止未封闭、原 CREATE 可能已派发、从未安装、完整原规则删除、规则不全／不匹配、删除失败事务中止、提交未知后只读核对。同一写事务验证所有原 GUID 和规则身份后才删除，读回事务核对缺失。组件输出仅代表网络范围。
- 命令使用 `tools.quality_gate.environment`、临时 `--basetemp` 及 `.venv/Scripts/python.exe -B tools/python-v20.py tools/quality_python.py -q -p no:cacheprovider --tb=short`。选取 infrastructure 的 `test_v20_guard_task_network.py`、`test_v20_wfp_install_transaction.py`、`test_v20_windows_wfp.py`、`test_v20_guard_action_journal.py`、`test_v20_runtime_launch_journal.py`、`test_v20_guard_recovery.py`。最终 **113 项通过**（7.19 秒），仅既有 Starlette 弃用提示。最终临时目录清理后已检查不存在。
- `python -m ruff format --no-cache --check backend/app` 277 文件通过，`ruff check --no-cache` 检查本轮两个源码和两个测试文件通过，`git diff --check` 通过。仅有既有前端文件的 CRLF 提示。
- WFP 删除／安装为 ABI 夹具证据。实际验证使用自有临时 NTFS 记录、Windows SID 派生及本机只读 API。受保护 SYSTEM Guard、真实 WFP 写删与仲裁、LPAC 连接、TASK 生产派发、已派发进程停止后的资源释放仍待。当前执行准入仍关闭。 [Windows WFP 事务](https://learn.microsoft.com/en-us/windows/win32/fwp/object-management)
