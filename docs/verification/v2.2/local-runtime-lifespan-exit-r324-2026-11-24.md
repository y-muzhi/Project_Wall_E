# V2.2 R324 启动器的关闭退出状态

2026-11-24（香港时间）。独立 `codex/2.2`，当前工作区未提交源码，Windows 项目固定 Uvicorn 0.54.0 与 FastAPI 0.142.2。临时测试监听仅为系统分配的 127.0.0.1 端口，随测试进程和套接字关闭，无应用数据库或现有用户服务。

- 原逻辑在 `server.run` 返回后只检查 `server.started`。用实际 FastAPI 和 Uvicorn 在独立回环 56362 复现。关闭钩子失败时 Uvicorn 记录 `shutdown_failed=True`，旧退出计算仍为 0。这会把可能尚未检查点完成的普通停止报告为进程成功。
- 所有既有普通、发布开放和只读入口共用原启动器配置。退出成功须已启动且 ASGI 已走完关闭、没有关闭失败或生命周期异常。固定 Uvicorn 自身的启动失败退出 3 保持，新增关闭失败出口 2。持久控制和宿主原运行停止核验继续独立判定。
- 用真实框架在同一个启动函数下验证正常关闭、启动失败、关闭失败，分别观察 0、3、2。初次测试误以为 Uvicorn 启动失败会正常返回，实际固定版本抛出 `SystemExit(3)`，夹具已按真实行为检查。
- `python -m pytest -q -p no:cacheprovider --basetemp <独立目录> backend/tests/infrastructure/test_v22_runtime_exit.py` 3 项通过。两个受影响文件的固定 Ruff 格式、F／I 及 `git diff --check` 通过。Windows 默认受限进程的回环初始化未返回，已关闭该独立进程，用获准的回环范围执行。
- Ubuntu 下普通应用的实际停机、SQLite 并发检查点失败和管理原停止回执需要实机联验。本检查没有演练最新固定候选的完整发布。
