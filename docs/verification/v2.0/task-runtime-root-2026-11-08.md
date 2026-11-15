# V2.0 独立受管执行父根

2026-11-08（Asia/Hong_Kong），Windows x64／NTFS，工作树基线 `28a7c9e`，固定 SQLite 3.54.1。对照 BE 7.3.1—7.3.3 及原 START_INSTANCE 工作区。 [独立迭代](../../iterations/pending/v2.0/WALL-E.首次工作区固定字节物化_V_2.0.md)

- 真实新建 `task-runtime`，读回保护 DACL 和原后端 SID 的非继承掩码 `0x001000a0`。原 FileID 可重开，错误 FileID、另一 SID、同名已有目录、路径交叠及卷／FileID 别名拒绝。原任务角色只在该独立根下创建。实际原 TASK 命名管道校验接入受信父根和当前后端令牌，受保护程序正向准入仍为夹具。 [Microsoft 文件权限](https://learn.microsoft.com/en-us/windows/win32/fileio/file-access-rights-constants)
- 本机带独立限制 SID 的真实 Windows 令牌，在无 Guard 排他句柄干扰时成功打开属性句柄并读回实际卷、FileID 和类型。请求枚举、创建、删除子项、删除根、改 DACL 或改所有者均为访问拒绝，授权也未继承给原根下的新目录。该令牌不是正式双账户或 LPAC。附加测试最初同时调用完整规范路径核对，`GetFinalPathNameByHandleW` 在这个受限夹具中失败，后续独立验证了文件身份读回。正常发布保留完整规范路径核对，正式异账户环境仍须实际走完该检查。 [Microsoft 规范路径 API](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfinalpathnamebyhandlew)
- 命令经 `tools.quality_gate.environment`、临时 `--basetemp`、`WALLE_TEST_CONTROLLER_POSITIVE=1`，运行 `.venv/Scripts/python.exe -B tools/python-v20.py tools/quality_python.py -q -p no:cacheprovider --tb=short`。选取 `test_v20_task_runtime_root.py`、`test_v20_windows_task_directories.py`、`test_task_runtime_workspace.py`、`test_v20_windows_access_check.py` 及 `test_v20_guard_control_git_transport.py` 的来源交接、宿主和已封存 TASK 场景，组合 **40 项通过**（21.66 秒）。最终根专项 **2 项通过**（0.76 秒）。仅既有 Starlette 弃用提示，临时目录均已清理。
- 应用 282 文件 Ruff 格式、4 个改动源码 Ruff lint 及 `git diff --check` 通过，Git 提示既有前端文件 CRLF。
- 正式 SYSTEM／普通后端的父路径和完整工作区交接尚待实测。只读依据受限写入、实际 LPAC、正式运行包和 Job 仍待，生产 PREPARE 仍未分配。
