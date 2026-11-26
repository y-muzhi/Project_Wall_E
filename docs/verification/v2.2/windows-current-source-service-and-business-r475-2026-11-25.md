# WALL-E V2.2 R475 Windows 当前源码服务与业务验证边界

日期：2026-11-25（香港时间）

## 范围

本轮接续 `codex/2.2` 与 `codex/2.2-integration` 两个隔离工作区，双方 HEAD 均为 `deacba8a9545122f35a2f85c125a354205e06461`。未改业务源码、Git 索引或 HEAD；未连接模型、计数、付费供应方或云资源，未触碰日常 `8001` 入口及业务库。

## 分支依赖环境

两个工作区各自的 `.venv` 已按 `backend/requirements.lock` 配置 31 个锁定发行包，每侧 2,440 个文件、33,788,415 字节；通过本地文件复制和每文件原子落盘建立独立副本，没有复用其他工作区的 site-packages 路径或解释器启动器。两侧 `python -m pip check` 均报告 `No broken requirements found`；Python 为 3.13.5，FastAPI 0.142.2、Uvicorn 0.54.0、jsonschema 4.26.0、httpx 0.28.1 与锁一致，核心包文件身份彼此独立。该结果证明本机测试依赖可用，不替代固定 Linux 运行包及候选准入。

## Windows 服务进程尝试

开发分支运行现有 `backend/tests/test_service_process.py::test_actual_cli_init_tcp_native_acceptance_second_process_refusal_graceful_close_and_restart`。测试只创建临时 SQLite，通过生产 `create_app` 工厂及真实 Uvicorn 子进程；模型环境变量被移除。测试自动挑端口的步骤由本轮 `sitecustomize` 固定到 `127.0.0.1:18101`，使用工作区专属临时目录。pytest 退出 1：就绪轮询报 `Actual service did not start`，未得到创建需求、停机及重启读回断言结果；清理钩子中的 `taskkill` 返回失败。随后按测试 PID、监听、owner 标记和完整路径核对：PID 已退出、18101 无监听、专属目录已清理。此失败不能表述为产品验证通过，也无法从空服务日志判定是服务启动还是本机 TCP 探测故障。集成分支未重复该服务测试。

## Windows ASGI 与命令测试尝试

两个分支并行运行 `test_service.py`、`test_create_requirement.py`、`test_save_manual_draft.py`、`test_v15_editing.py`，均在 180 秒超时前无完成摘要；按进程快照与 owner 路径清理两侧测试进程和临时目录。开发分支另以 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` 单跑 `test_service.py`；90 秒后仍停在首个 ASGI lifespan 用例，pytest PID 随后退出，专属目录已清理。上述均记为未完成，不计通过。

为定位契约，开发分支单独运行 `test_create_requirement.py` 与 `test_save_manual_draft.py`，收集 26 项，结果为 34 failed、3 passed、14 warnings、17 个子项通过。需求用例提交的是 V1.5 的 `template_key`、`template_version`、`initialization_mode` 字段，现行 V2.2 请求契约将其作为 `UNKNOWN_FIELD` 拒绝；人工草稿旧用例在 Windows 本地数据库锁路径返回 `StorageUnavailable`。这些旧版测试不能作为 V2.2 Linux 普通业务结果的判定依据，失败原文没有保留。所有工作区专属临时文件已清理。

## 结论与下一步

本轮没有新增通过的服务／浏览器验收。最近的当前源码 Linux 证据仍为 [R474](linux-current-source-twin-regression-r474-2026-11-25.md)：两工作区各自在无网 x86_64 TCG 来宾运行 24 个 V2.2 Linux 专项并以退出码 0 结束，但它不覆盖本轮未完成的普通服务进程闭环。

下一步沿用 R474 的隔离原则，为当前两工作区分别在全新无网 Linux 来宾运行现有服务进程专项，核对真实需求创建、正常关闭、独立重启和原数据读回；随后补人工文档编辑／保存／重启读回及开发／集成交叉拒绝的当前源码验证。不得把旧 R399／R455 候选浏览器证据挪作当前源码结果。若 Linux 专项通过，再决定当前普通界面浏览器路径所需的隔离执行环境。正式受信提交、候选发布、云资源及生产接入依原授权边界处理。
