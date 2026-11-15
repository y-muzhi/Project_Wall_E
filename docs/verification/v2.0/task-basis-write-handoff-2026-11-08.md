# V2.0 只读依据单文件的原写句柄交接

2026-11-08（Asia/Hong_Kong），Windows x64／NTFS，工作树基线 `28a7c9e`，固定 SQLite 3.54.1。对照 BE 7.3.2 和原 START_INSTANCE 依据边界。 [独立迭代](../../iterations/pending/v2.0/WALL-E.启动固定依据准备_V_2.0.md)

- 使用自有 Job 中的真实普通后端子进程、原 ProcessLock、原 Guard Journal 与独立任务目录。Guard 只接收固定编号、摘要、长度和原过程事实。NTFS 实际文件 owner／DACL／标签读回，真实跨进程句柄为 `FILE_WRITE_DATA | FILE_READ_ATTRIBUTES | SYNCHRONIZE`，不可继承。后端先核对原进程、scope／绑定、FileID 和实际授权，再从原封存写入。测试进程通过临时文件交换元数据，生产认证管道尚未接该动作。
- 正向覆盖非 ASCII UTF-8、CRLF 和空文件，后端关闭原 writer 后由 Guard 持原无写共享 pin，再由后端读回摘要。写端未关闭时 Windows 返回共享冲突 32，Guard 保留原目录 owner。重复编号、错误绑定或回执拒绝，取消后原 writer 关闭，同长度篡改仍因摘要不符拒绝。Guard 没有正文读取调用。 [Microsoft 句柄复制](https://learn.microsoft.com/en-us/windows/win32/api/handleapi/nf-handleapi-duplicatehandle) [Microsoft 文件共享](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)
- 命令经 `tools.quality_gate.environment`、临时 `--basetemp` 和 `WALLE_TEST_CONTROLLER_POSITIVE=1` 执行 `.venv/Scripts/python.exe -B tools/python-v20.py tools/quality_python.py -q -p no:cacheprovider --tb=short`。选取 `test_v20_windows_task_basis.py`、`test_task_start_basis.py`、`test_task_start_conditions.py`、`test_v20_windows_task_directories.py` 与 `test_v20_task_runtime_root.py`。首轮专项 3 通过（5.39 秒），加入未关闭时目录保留回归后最终 **26 项通过**（132.19 秒）。仅既有 Starlette 弃用提示，临时目录均已清理并核对不存在。
- 283 文件 Ruff 格式、3 个改动应用源码 Ruff lint、`git diff --check` 通过。首轮 lint 发现一个新导入顺序问题，已修正。Git 提示既有前端文件 CRLF。
- 证据覆盖真实同账户跨进程句柄与 NTFS 结构。正式异账户、生产认证管道、整个依据组原回执、实际 LPAC、正式运行包、任务启动和停止后的文件清理仍待。原执行准入保持阻断。
