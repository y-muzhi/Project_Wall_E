# V2.0 TASK 原 NTFS 来源交接

2026-11-08（Asia/Hong_Kong），Windows x64／NTFS，工作树基线 `28a7c9e`，固定 SQLite 3.54.1。对照 BE 0.17-draft-17 §7.3.1—7.3.3 和 §7.4.4。 [独立迭代](../../iterations/pending/v2.0/WALL-E.Guard原技术动作与资源准备实施细化_V_2.0.md)

- 正常后台 `CHECK_CONDITIONS` 在原父根、工作区、树清单、依据封存 FileID 均固定时复验正文、清单和原代次。已有旧清单、内容变更、停止、超时和容量异常仍沿原失败或停止语义。内容通过后仍分别检查执行器、运行包、LPAC 与 WFP。
- 实际命名管道中的普通 Windows 子进程持有 ProcessLock 和原属性句柄。Guard 用已登记父根身份及固定 nonce 推导名称，复制实际原进程的属性句柄并核对实际卷／FileID／类型和访问掩码。正向程序包准入为夹具。验证拒绝交叉替换对象、带正文读取权的句柄、非法 nonce、已封闭作用域。PREPARE 回执保持 UNKNOWN，未形成任务原接收／Job 或其他任务运行资源。
- 使用 `tools.quality_gate.environment`、临时 `--basetemp` 和 `.venv/Scripts/python.exe -B tools/python-v20.py tools/quality_python.py -q -p no:cacheprovider --tb=short`。`backend/tests/code_tasks/test_task_start_conditions.py` 和 `test_v20_guard_control_git_transport.py` 的 TASK 来源交接、原元数据句柄及已封存 TASK 管道场景组合 **16 项通过**（93.39 秒）。追加正文句柄负向后复跑来源交接及固定 Git 元数据 SHA-1／SHA-256，**3 项通过**（88.83 秒），其中来源交接为复跑。仅既有 Starlette 弃用提示。两次专用临时目录均已清理并核对。
- `ruff format --no-cache --check backend/app` 280 文件通过，6 个修改应用文件 `ruff check --no-cache` 通过，`git diff --check` 通过。既有前端文件有 CRLF 提示。
- 实际任务派发、依据只读副本、LPAC 有效访问、受管运行包／配置、入口／原 Job、受保护 SYSTEM 安装及真实 WFP 写删仍待。验证环境未使用真实供应方或业务数据。
