# V2.0 C05 按原请求主动续核验证

2026-11-08。db20-r20，Windows NTFS，固定 SQLite／MinGit，隔离应用、仓库及 Guard 管道。此批涉及原请求重放、线程提示、原作用域只读续核及共用引用核对。未做页面、系统安装或真实供应方验证。

- 隔离应用和元数据回归 65 项通过。实际 ASGI 验证首次受理、同键不同输入冲突、两次同键同输入重放合并为原操作的一条提示、普通 GET 无提示，最终只有一个原操作。
- 原 202 仍从持久回执返回。内存提示由专用线程持有，最多 256 个并去重，生命周期独立于原受理。线程依据原操作和原步骤判断是否续核，仍由 Guard 证据和同一原提交决定结果。
- 首次 ASGI 专项的隔离应用没有预设执行线程字段，测试夹具改为显式注入，专项和 65 项回归均复测通过。
- 实际 Guard 管道和 MinGit 专项 4 项通过。原引用暂缺时主动续核留下 UNKNOWN，VERIFY 保持 PENDING，未占用新的只读步骤。恢复为 loose 或 packed 后，经同一后台执行者保存原快照。正式 C05 HTTP 到 Git、跨后端清理及只读恢复均通过。预检时限检查加入后，packed 续核 1 项再次通过。
- 基线续核预检复用受租约保护的 loose／packed 引用读取，原提交核实前仍无新 VERIFY 范围。预检前后核对取消和时限。

使用项目 .venv、tools/python-v20.py、tools/quality_python.py 和 tools.quality_gate.environment。回归范围为 backend/tests/code_tasks/test_repository_baseline_acceptance.py、test_repository_acceptance.py、test_repository_operations.py、backend/tests/infrastructure/test_v20_git_repository_metadata.py。实际 Guard 管道从 backend/tests/infrastructure/test_v20_guard_control_git_transport.py 选 BASELINE_RECOVERY、BASELINE_HTTP 和 restarted_baseline。测试输出在自动清理的临时目录。最终 Ruff 格式及改动模块 lint、diff 检查通过。产物清理扫描为 0 个 JSON、0 张截图。

尚待 API06／19 的私有查询作用域、详情与文件分页入口、任务创建页面和正式部署。
